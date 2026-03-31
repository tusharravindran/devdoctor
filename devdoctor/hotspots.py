"""Endpoint hotspot ranking across saved project sessions and the live run."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .issues import build_noise_config
from .utils.project import get_sessions_dir

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}"
    r"-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_INT_SEGMENT_RE = re.compile(r"^\d+$")


class HotspotTracker:
    """Aggregate endpoint hotspots from saved snapshots plus the live session."""

    def __init__(
        self,
        request_tracker,
        noise_config: Optional[Dict[str, Any]] = None,
        sessions_dir: Optional[Path] = None,
    ) -> None:
        self._request_tracker = request_tracker
        self._sessions_dir = (sessions_dir or get_sessions_dir()).expanduser().resolve()
        noise = build_noise_config(noise_config)
        self._ignore_patterns = [
            re.compile(str(pattern), re.IGNORECASE)
            for pattern in noise.get("ignore_patterns", [])
            if pattern
        ]
        self._cached_signature: Optional[Tuple[Any, ...]] = None
        self._cached_hotspots: List[Dict[str, Any]] = []

    def hotspots(self) -> List[Dict[str, Any]]:
        signature = self._signature()
        if signature == self._cached_signature:
            return list(self._cached_hotspots)

        requests = self._saved_requests()
        requests.extend(self._current_requests())
        hotspots = self._aggregate(requests)
        self._cached_signature = signature
        self._cached_hotspots = hotspots
        return list(hotspots)

    def count(self) -> int:
        return len(self.hotspots())

    def _signature(self) -> Tuple[Any, ...]:
        files = sorted(self._sessions_dir.glob("session-*.json"))
        file_bits = []
        for path in files:
            try:
                stat = path.stat()
            except OSError:
                continue
            file_bits.append((path.name, stat.st_mtime_ns, stat.st_size))

        live_bits = []
        for trace in self._request_tracker.traces():
            live_bits.append(
                (
                    trace.get("request_id"),
                    trace.get("last_seen_at"),
                    trace.get("duration"),
                    trace.get("warning_count"),
                    trace.get("error_count"),
                )
            )

        return tuple(file_bits), tuple(live_bits)

    def _saved_requests(self) -> List[Dict[str, Any]]:
        requests: List[Dict[str, Any]] = []
        for path in sorted(self._sessions_dir.glob("session-*.json")):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except (OSError, json.JSONDecodeError):
                continue

            for trace in payload.get("requests", []):
                if not isinstance(trace, dict):
                    continue
                enriched = dict(trace)
                enriched["_source_session"] = path.name
                requests.append(enriched)

        return requests

    def _current_requests(self) -> List[Dict[str, Any]]:
        requests: List[Dict[str, Any]] = []
        for trace in self._request_tracker.traces():
            enriched = dict(trace)
            enriched["_source_session"] = "__live__"
            requests.append(enriched)
        return requests

    def _aggregate(self, requests: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        timelines_by_endpoint: Dict[str, Dict[str, float]] = {}
        requests_by_endpoint: Dict[str, List[Dict[str, Any]]] = {}

        for trace in requests:
            endpoint = self._endpoint_label(trace)
            if not endpoint:
                continue

            group = grouped.get(endpoint)
            if group is None:
                group = {
                    "endpoint": endpoint,
                    "method": trace.get("method"),
                    "path": self._normalize_path(str(trace.get("path") or "")) or None,
                    "count": 0,
                    "session_ids": set(),
                    "durations": [],
                    "warning_total": 0,
                    "error_total": 0,
                    "ignored": self._is_ignored(endpoint, trace),
                }
                grouped[endpoint] = group
                timelines_by_endpoint[endpoint] = {}
                requests_by_endpoint[endpoint] = []

            group["count"] += 1
            group["session_ids"].add(str(trace.get("_source_session") or ""))
            group["warning_total"] += int(trace.get("warning_count") or 0)
            group["error_total"] += int(trace.get("error_count") or 0)

            duration_ms = self._to_ms(trace.get("duration") or trace.get("timeline_total_ms"))
            if duration_ms is not None:
                group["durations"].append(duration_ms)

            requests_by_endpoint[endpoint].append(trace)

            for item in trace.get("timeline_breakdown") or []:
                if not isinstance(item, dict):
                    continue
                kind = str(item.get("kind") or "other")
                duration = self._to_ms(item.get("duration_ms"))
                if duration is None:
                    continue
                timelines = timelines_by_endpoint[endpoint]
                timelines[kind] = timelines.get(kind, 0.0) + duration

        hotspots: List[Dict[str, Any]] = []
        for endpoint, group in grouped.items():
            durations = sorted(group["durations"])
            p95_ms = self._percentile(durations, 95)
            avg_ms = round(sum(durations) / len(durations), 1) if durations else None
            max_ms = round(max(durations), 1) if durations else None
            retry_count = self._estimate_retries(requests_by_endpoint[endpoint])
            dominant_kind, dominant_ms = self._dominant_timeline_kind(timelines_by_endpoint[endpoint])
            dominant_label = self._kind_label(dominant_kind) if dominant_kind else None
            ignored = bool(group["ignored"])

            summary = self._summary_text(
                ignored=ignored,
                p95_ms=p95_ms,
                retry_count=retry_count,
                warning_total=group["warning_total"],
                error_total=group["error_total"],
            )
            score = self._score(
                ignored=ignored,
                p95_ms=p95_ms,
                retry_count=retry_count,
                error_total=group["error_total"],
                warning_total=group["warning_total"],
                count=group["count"],
            )

            hotspots.append(
                {
                    "endpoint": endpoint,
                    "count": group["count"],
                    "session_count": len(group["session_ids"]),
                    "p95_ms": p95_ms,
                    "avg_ms": avg_ms,
                    "max_ms": max_ms,
                    "retry_count": retry_count,
                    "warning_total": group["warning_total"],
                    "error_total": group["error_total"],
                    "ignored": ignored,
                    "summary": summary,
                    "dominant_kind": dominant_kind,
                    "dominant_label": dominant_label,
                    "dominant_ms": round(dominant_ms, 1) if dominant_ms is not None else None,
                    "score": score,
                }
            )

        return sorted(
            hotspots,
            key=lambda item: (
                item["ignored"],
                -(item["score"]),
                -(item["p95_ms"] or 0.0),
                -(item["retry_count"]),
                -(item["count"]),
                item["endpoint"],
            ),
        )

    def _endpoint_label(self, trace: Dict[str, Any]) -> Optional[str]:
        method = str(trace.get("method") or "").strip().upper()
        path = self._normalize_path(str(trace.get("path") or ""))
        if method and path:
            return f"{method} {path}"
        if path:
            return path
        controller = str(trace.get("controller") or "").strip()
        action = str(trace.get("action") or "").strip()
        if controller and action:
            return f"{controller}#{action}"
        if controller:
            return controller
        return str(trace.get("title") or "").strip() or None

    def _normalize_path(self, path: str) -> str:
        raw = (path or "").strip()
        if not raw:
            return ""

        raw = raw.split("?", 1)[0]
        if not raw.startswith("/"):
            return raw

        parts = []
        for part in raw.split("/"):
            if not part:
                continue
            if _INT_SEGMENT_RE.match(part):
                parts.append(":id")
                continue
            if _UUID_RE.fullmatch(part):
                parts.append(":id")
                continue
            parts.append(part)
        return "/" + "/".join(parts)

    def _estimate_retries(self, requests: Iterable[Dict[str, Any]]) -> int:
        attempts = sorted(
            (trace for trace in requests if trace.get("started_at")),
            key=lambda trace: str(trace.get("started_at")),
        )
        retries = 0
        previous_started: Optional[datetime] = None

        for trace in attempts:
            started_at = self._parse_dt(str(trace.get("started_at") or ""))
            if started_at is None:
                continue

            status = str(trace.get("status") or "")
            error_count = int(trace.get("error_count") or 0)
            warning_count = int(trace.get("warning_count") or 0)

            if previous_started is not None:
                gap = (started_at - previous_started).total_seconds()
                if gap <= 10 and (status.startswith("5") or error_count > 0 or warning_count > 0):
                    retries += 1

            previous_started = started_at

        return retries

    def _summary_text(
        self,
        *,
        ignored: bool,
        p95_ms: Optional[float],
        retry_count: int,
        warning_total: int,
        error_total: int,
    ) -> str:
        if ignored:
            return "noisy ignored"
        if retry_count > 0:
            suffix = "retry" if retry_count == 1 else "retries"
            return f"{retry_count} {suffix}"
        if p95_ms is not None:
            return f"P95 {self._format_ms(p95_ms)}"
        if error_total > 0:
            suffix = "error" if error_total == 1 else "errors"
            return f"{error_total} {suffix}"
        if warning_total > 0:
            suffix = "warning" if warning_total == 1 else "warnings"
            return f"{warning_total} {suffix}"
        return "active"

    def _score(
        self,
        *,
        ignored: bool,
        p95_ms: Optional[float],
        retry_count: int,
        error_total: int,
        warning_total: int,
        count: int,
    ) -> float:
        if ignored:
            return -1.0

        return (
            float(p95_ms or 0.0)
            + (retry_count * 180.0)
            + (error_total * 120.0)
            + (warning_total * 18.0)
            + (count * 4.0)
        )

    def _dominant_timeline_kind(self, totals: Dict[str, float]) -> Tuple[Optional[str], Optional[float]]:
        if not totals:
            return None, None
        kind, duration = max(totals.items(), key=lambda item: item[1])
        return kind, duration

    def _kind_label(self, kind: Optional[str]) -> Optional[str]:
        if not kind:
            return None
        labels = {
            "controller": "controller",
            "app": "app",
            "db": "db",
            "cache": "cache",
            "external": "external api",
            "render": "render",
            "other": "other",
        }
        return labels.get(kind, kind.replace("_", " "))

    def _is_ignored(self, endpoint: str, trace: Dict[str, Any]) -> bool:
        if not self._ignore_patterns:
            return False
        haystacks = [
            endpoint,
            str(trace.get("path") or ""),
            str(trace.get("title") or ""),
        ]
        for pattern in self._ignore_patterns:
            if any(value and pattern.search(value) for value in haystacks):
                return True
        return False

    def _percentile(self, values: Sequence[float], percentile: int) -> Optional[float]:
        if not values:
            return None
        rank = max(1, math.ceil((percentile / 100.0) * len(values)))
        return round(values[rank - 1], 1)

    def _format_ms(self, duration_ms: float) -> str:
        return f"{float(duration_ms):.1f}".rstrip("0").rstrip(".") + "ms"

    def _parse_dt(self, value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _to_ms(self, value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
