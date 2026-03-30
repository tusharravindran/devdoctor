"""Request trace grouping helpers for interleaved application logs."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

QUERY_TYPES = {"db_query", "query", "eager_load"}
WARNING_TYPES = {"warning", "deprecation", "eager_load", "timeout"}
ERROR_TYPES = {
    "error",
    "exception",
    "panic",
    "oom",
    "connection",
    "concurrency",
    "unhandled",
    "stackoverflow",
    "traceback",
}

_REQUEST_ID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}"
    r"-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_START_RE = re.compile(
    r'Started (?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) "(?P<path>[^"]+)"'
)
_ACTOR_RE = re.compile(
    r"\[(?P<user>u_[^\]]+)\]\s+(?P<actor>.+?)\s+"
    r"(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(?P<path>\S+)"
)
_PROCESSING_RE = re.compile(
    r"Processing by (?P<controller>[^\s]+)#(?P<action>[^\s]+) as (?P<format>\w+)"
)
_COMPLETED_RE = re.compile(
    r"Completed (?P<status>\d{3}) (?P<status_text>.+?) in (?P<duration>\d+(?:\.\d+)?)ms"
)
_PARAMETERS_RE = re.compile(r"Parameters: (?P<parameters>.+)$")
_RENDERED_RE = re.compile(r"Rendered (?P<template>.+?) \(Duration: (?P<duration>\d+(?:\.\d+)?)ms")


class RequestTraceTracker:
    """Group interleaved log lines into request-scoped traces."""

    def __init__(self) -> None:
        self._traces: Dict[str, Dict[str, Any]] = {}
        self._sequence = 0

    def ingest(self, event: Dict[str, Any]) -> None:
        raw = str(event.get("raw") or "")
        request_id = str(event.get("request_id") or "") or self._extract_request_id(raw)
        if not request_id:
            return

        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        trace = self._traces.get(request_id)
        if trace is None:
            trace = {
                "request_id": request_id,
                "sequence": self._sequence,
                "method": None,
                "path": None,
                "actor": None,
                "user": None,
                "controller": None,
                "action": None,
                "format": None,
                "status": None,
                "status_text": None,
                "duration": None,
                "started_at": ts,
                "last_seen_at": ts,
                "query_count": 0,
                "warning_count": 0,
                "error_count": 0,
                "render_count": 0,
                "events": [],
            }
            self._traces[request_id] = trace
            self._sequence += 1

        trace["last_seen_at"] = ts
        trace["events"].append(self._serialize_event(event, raw, ts))
        self._update_metadata(trace, event, raw)

    def traces(self) -> List[Dict[str, Any]]:
        """Return request traces sorted by most recent activity."""
        return sorted(
            [self._serialize_trace(trace) for trace in self._traces.values()],
            key=lambda trace: (trace.get("completed") is False, trace["last_seen_at"], trace["sequence"]),
            reverse=True,
        )

    def snapshot_traces(self) -> List[Dict[str, Any]]:
        """Return request traces for snapshot persistence."""
        return self.traces()

    def count(self) -> int:
        return len(self._traces)

    def get_trace(self, request_id: str) -> Optional[Dict[str, Any]]:
        trace = self._traces.get(request_id)
        if trace is None:
            return None
        return self._serialize_trace(trace)

    def _serialize_event(self, event: Dict[str, Any], raw: str, ts: str) -> Dict[str, Any]:
        return {
            "ts": ts,
            "type": event.get("type", "log"),
            "message": event.get("message"),
            "duration": event.get("duration"),
            "table": event.get("table"),
            "raw": raw,
            "stage": self._infer_stage(raw),
        }

    def _serialize_trace(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        method = trace.get("method")
        path = trace.get("path")
        controller = trace.get("controller")
        action = trace.get("action")
        status = trace.get("status")
        title = " ".join(part for part in [method, path] if part).strip()
        if not title and controller:
            title = controller if not action else f"{controller}#{action}"
        if not title:
            title = trace["request_id"]

        search_parts = [
            trace["request_id"],
            method or "",
            path or "",
            controller or "",
            action or "",
            trace.get("actor") or "",
            trace.get("user") or "",
            str(status or ""),
        ]

        return {
            "request_id": trace["request_id"],
            "sequence": trace["sequence"],
            "title": title,
            "method": method,
            "path": path,
            "actor": trace.get("actor"),
            "user": trace.get("user"),
            "controller": controller,
            "action": action,
            "format": trace.get("format"),
            "status": status,
            "status_text": trace.get("status_text"),
            "duration": trace.get("duration"),
            "started_at": trace["started_at"],
            "last_seen_at": trace["last_seen_at"],
            "query_count": trace["query_count"],
            "warning_count": trace["warning_count"],
            "error_count": trace["error_count"],
            "render_count": trace["render_count"],
            "completed": trace.get("status") is not None,
            "search_text": " ".join(part for part in search_parts if part).strip(),
            "events": list(trace["events"]),
        }

    def _update_metadata(self, trace: Dict[str, Any], event: Dict[str, Any], raw: str) -> None:
        start_match = _START_RE.search(raw)
        if start_match:
            trace["method"] = start_match.group("method")
            trace["path"] = start_match.group("path")

        actor_match = _ACTOR_RE.search(raw)
        if actor_match:
            trace["actor"] = actor_match.group("actor")
            trace["user"] = actor_match.group("user")
            trace["method"] = trace["method"] or actor_match.group("method")
            trace["path"] = trace["path"] or actor_match.group("path")

        processing_match = _PROCESSING_RE.search(raw)
        if processing_match:
            trace["controller"] = processing_match.group("controller")
            trace["action"] = processing_match.group("action")
            trace["format"] = processing_match.group("format")

        completed_match = _COMPLETED_RE.search(raw)
        if completed_match:
            trace["status"] = completed_match.group("status")
            trace["status_text"] = completed_match.group("status_text")
            trace["duration"] = completed_match.group("duration")

        rendered_match = _RENDERED_RE.search(raw)
        if rendered_match:
            trace["render_count"] += 1

        if event.get("type") in QUERY_TYPES:
            trace["query_count"] += 1
        if event.get("type") in WARNING_TYPES:
            trace["warning_count"] += 1
        if event.get("type") in ERROR_TYPES:
            trace["error_count"] += 1

        parameters_match = _PARAMETERS_RE.search(raw)
        if parameters_match and trace.get("path") is None:
            trace["path"] = parameters_match.group("parameters")

    def _extract_request_id(self, raw: str) -> Optional[str]:
        match = _REQUEST_ID_RE.search(raw)
        return match.group(0) if match else None

    def _infer_stage(self, raw: str) -> str:
        if _START_RE.search(raw):
            return "started"
        if _PROCESSING_RE.search(raw):
            return "processing"
        if _PARAMETERS_RE.search(raw):
            return "parameters"
        if _RENDERED_RE.search(raw):
            return "rendered"
        if _COMPLETED_RE.search(raw):
            return "completed"
        if "↳" in raw:
            return "trace"
        return "event"
