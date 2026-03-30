"""Issue fingerprinting, grouping, and suggestion helpers."""

from __future__ import annotations

import difflib
import hashlib
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_NOISE_CONFIG: Dict[str, Any] = {
    "min_count_to_show": 1,
    "ignore_patterns": [],
    "silence_after_clear": True,
}

WARNING_TYPES = {"warning", "deprecation", "eager_load", "timeout"}
TRACKED_TYPES = WARNING_TYPES | {
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

_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}"
    r"-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b|\b[0-9a-fA-F]{10,}\b")
_NUM_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_WS_RE = re.compile(r"\s+")
_PORT_COLLISION_RE = re.compile(
    r"(?:EADDRINUSE|address already in use).*?(?::|port[ =])(?P<port>\d{2,5})\b",
    re.IGNORECASE,
)
_PORT_SEARCH_SUFFIXES = {
    ".env",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".properties",
    ".js",
    ".ts",
    ".py",
    ".go",
}


def build_noise_config(raw_noise: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Merge user-provided noise controls with safe defaults."""
    noise = dict(DEFAULT_NOISE_CONFIG)
    if not isinstance(raw_noise, dict):
        return noise

    if isinstance(raw_noise.get("min_count_to_show"), int):
        noise["min_count_to_show"] = max(1, raw_noise["min_count_to_show"])

    ignore_patterns = raw_noise.get("ignore_patterns")
    if isinstance(ignore_patterns, list):
        noise["ignore_patterns"] = [str(pattern) for pattern in ignore_patterns if pattern]

    if isinstance(raw_noise.get("silence_after_clear"), bool):
        noise["silence_after_clear"] = raw_noise["silence_after_clear"]

    return noise


def rebuild_issues_from_snapshot(
    payload: Optional[Dict[str, Any]],
    noise_config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return issues for a stored snapshot, rebuilding them if needed."""
    if not isinstance(payload, dict):
        return []

    issues = payload.get("issues")
    if isinstance(issues, list):
        return [issue for issue in issues if isinstance(issue, dict)]

    tracker = IssueTracker(noise_config=noise_config)
    for event in payload.get("events", []):
        if isinstance(event, dict):
            tracker.ingest(event)
    return tracker.snapshot_issues(final=True)


class IssueTracker:
    """Track canonical issues for the current session and compare to a baseline."""

    def __init__(
        self,
        noise_config: Optional[Dict[str, Any]] = None,
        previous_snapshot: Optional[Dict[str, Any]] = None,
        autofix_mode: str = "off",
    ) -> None:
        self._noise = build_noise_config(noise_config)
        self._ignore_patterns = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self._noise["ignore_patterns"]
        ]
        self._autofix_mode = autofix_mode
        self._project_root = Path.cwd()
        self._issues: Dict[str, Dict[str, Any]] = {}
        self._previous_issues = self._load_previous_issues(previous_snapshot)

    def ingest(self, event: Dict[str, Any]) -> None:
        """Add a new parsed event to the issue model."""
        if event.get("type") not in TRACKED_TYPES:
            return

        issue_seed = self._build_issue_seed(event)
        if issue_seed is None:
            return

        fingerprint = issue_seed["fingerprint"]
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        issue = self._issues.get(fingerprint)
        if issue is None:
            issue = {
                "fingerprint": fingerprint,
                "type": issue_seed["type"],
                "title": issue_seed["title"],
                "count": 0,
                "first_seen_at": now,
                "last_seen_at": now,
                "latest_example": {},
                "why": issue_seed["why"],
                "suggestion": issue_seed["suggestion"],
                "confidence": issue_seed["confidence"],
                "risk": issue_seed["risk"],
                "ignored": issue_seed["ignored"],
                "autofix": issue_seed.get("autofix"),
                "status_override": None,
            }
            self._issues[fingerprint] = issue

        issue["count"] += 1
        issue["last_seen_at"] = now
        issue["latest_example"] = {
            "raw": event.get("raw", ""),
            "message": event.get("message"),
            "table": event.get("table"),
            "duration": event.get("duration"),
            "request_id": event.get("request_id"),
        }
        if issue_seed.get("autofix") and not issue.get("autofix"):
            issue["autofix"] = issue_seed["autofix"]

    def autofix_issues(self) -> List[Dict[str, Any]]:
        """Issues with structured autofix plans for suggest/apply flows."""
        issues = []
        for issue in self._issues.values():
            if issue.get("ignored"):
                continue
            if not issue.get("autofix"):
                continue
            issues.append(self._serialize_issue(issue))
        return issues

    def mark_autofix_result(self, fingerprint: str, result: Dict[str, Any]) -> None:
        issue = self._issues.get(fingerprint)
        if issue is None:
            return

        issue["status_override"] = result.get("status")
        autofix = dict(issue.get("autofix") or {})
        autofix.update(result)
        issue["autofix"] = autofix

    def update_autofix_plan(self, fingerprint: str, autofix: Dict[str, Any]) -> None:
        issue = self._issues.get(fingerprint)
        if issue is None:
            return
        issue["autofix"] = dict(autofix)

    def warning_issues(self) -> List[Dict[str, Any]]:
        """Visible warning issues for the Warnings tab."""
        return [
            issue
            for issue in self._sorted_current_issues()
            if issue["type"] in WARNING_TYPES
            and issue["count"] >= self._noise["min_count_to_show"]
            and issue["status"] != "ignored"
        ]

    def suggestion_issues(self, final: bool = False) -> List[Dict[str, Any]]:
        """Actionable issue list for Suggestions."""
        issues = [
            issue
            for issue in self._sorted_current_issues()
            if issue["status"] != "ignored"
        ]
        if final:
            issues.extend(self.cleared_issues())
        return issues

    def cleared_issues(self) -> List[Dict[str, Any]]:
        """Issues present in the previous run but absent in the current one."""
        cleared: List[Dict[str, Any]] = []
        for fingerprint, previous in self._previous_issues.items():
            if fingerprint in self._issues:
                continue

            cleared_issue = dict(previous)
            cleared_issue["status"] = "cleared"
            cleared_issue["count"] = previous.get("count", 0)
            cleared.append(cleared_issue)

        return sorted(
            cleared,
            key=lambda issue: (
                issue["type"] not in WARNING_TYPES,
                issue.get("title", ""),
            ),
        )

    def snapshot_issues(self, final: bool = False) -> List[Dict[str, Any]]:
        """Serialized issues suitable for JSON snapshots."""
        issues = self._sorted_current_issues(include_ignored=True)
        if final:
            issues.extend(self.cleared_issues())
        return issues

    def tab_counts(self, final: bool = False) -> Dict[str, int]:
        """Counts for issue-backed tabs."""
        return {
            "warnings": len(self.warning_issues()),
            "suggestions": len(self.suggestion_issues(final=final)),
            "autofix": len(self.autofix_issues()),
        }

    def _load_previous_issues(
        self,
        previous_snapshot: Optional[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        previous = {}
        for issue in rebuild_issues_from_snapshot(previous_snapshot, self._noise):
            status = issue.get("status", "detected")
            if status == "ignored":
                continue
            if status == "cleared" and self._noise["silence_after_clear"]:
                continue
            fingerprint = issue.get("fingerprint")
            if fingerprint:
                previous[fingerprint] = issue
        return previous

    def _sorted_current_issues(
        self,
        include_ignored: bool = False,
    ) -> List[Dict[str, Any]]:
        issues = [self._serialize_issue(issue) for issue in self._issues.values()]
        if not include_ignored:
            issues = [issue for issue in issues if issue["status"] != "ignored"]
        return sorted(
            issues,
            key=lambda issue: (
                issue["status"] == "ignored",
                issue["type"] not in WARNING_TYPES,
                -issue["count"],
                issue["title"],
            ),
        )

    def _serialize_issue(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        suggestion = issue.get("suggestion")
        confidence = issue.get("confidence")
        status = issue.get("status_override")
        if not status:
            status = "ignored" if issue.get("ignored") else "detected"
        if suggestion and status == "detected":
            status = "suggested"

        autofix = issue.get("autofix")
        if self._autofix_mode == "off" and status not in {"applied", "failed"}:
            autofix = None

        return {
            "fingerprint": issue["fingerprint"],
            "type": issue["type"],
            "title": issue["title"],
            "count": issue["count"],
            "first_seen_at": issue["first_seen_at"],
            "last_seen_at": issue["last_seen_at"],
            "latest_example": issue["latest_example"],
            "why": issue.get("why"),
            "suggestion": suggestion,
            "confidence": confidence,
            "risk": issue.get("risk"),
            "status": status,
            "autofix": autofix,
        }

    def _build_issue_seed(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        event_type = str(event.get("type") or "log")
        table = self._clean_text(event.get("table"))
        message = self._clean_text(event.get("message"))
        raw = self._clean_text(event.get("raw"))
        bullet_mode = self._clean_text(event.get("bullet_mode")).lower()

        if event_type == "eager_load" and not table and not message:
            return None

        title = self._issue_title(event_type, table, message, raw, bullet_mode)
        why = self._issue_why(event_type, table, message, raw, bullet_mode)
        suggestion, confidence, risk = self._issue_suggestion(
            event_type,
            table,
            message,
            raw,
            bullet_mode,
        )
        autofix = self._issue_autofix(
            event_type,
            table,
            message,
            raw,
            bullet_mode,
            event,
        )

        fingerprint_source = self._fingerprint_source(
            event_type,
            table,
            message,
            raw,
            bullet_mode,
        )
        fingerprint = hashlib.sha1(fingerprint_source.encode("utf-8")).hexdigest()[:16]
        ignored = self._matches_ignore_patterns(
            value
            for value in (title, table, message, raw)
            if value
        )

        return {
            "fingerprint": fingerprint,
            "type": event_type,
            "title": title,
            "why": why,
            "suggestion": suggestion,
            "confidence": confidence,
            "risk": risk,
            "ignored": ignored,
            "autofix": autofix,
        }

    def _fingerprint_source(
        self,
        event_type: str,
        table: str,
        message: str,
        raw: str,
        bullet_mode: str = "",
    ) -> str:
        parts = [event_type]
        if bullet_mode:
            parts.append(bullet_mode)
        if table:
            parts.append(table.lower())
        if message:
            parts.append(self._normalize_fingerprint_text(message))
        elif raw:
            parts.append(self._normalize_fingerprint_text(raw))
        return "|".join(parts)

    def _matches_ignore_patterns(self, values: Iterable[str]) -> bool:
        for value in values:
            for pattern in self._ignore_patterns:
                if pattern.search(value):
                    return True
        return False

    def _clean_text(self, value: Any) -> str:
        return str(value).strip() if value is not None else ""

    def _normalize_fingerprint_text(self, text: str) -> str:
        cleaned = text.lower()
        cleaned = _UUID_RE.sub("<uuid>", cleaned)
        cleaned = _HEX_RE.sub("<hex>", cleaned)
        cleaned = _NUM_RE.sub("<num>", cleaned)
        cleaned = _WS_RE.sub(" ", cleaned)
        return cleaned.strip()

    def _issue_title(
        self,
        event_type: str,
        table: str,
        message: str,
        raw: str,
        bullet_mode: str = "",
    ) -> str:
        if event_type == "eager_load":
            assoc = self._association_summary(message, limit=2)
            prefix = "Unused eager loading" if bullet_mode == "avoid" else "N+1 eager loading"
            if table and assoc:
                return f"{prefix} on {table} -> {assoc}"
            if table:
                return f"{prefix} on {table}"
            return f"{prefix} detected"

        if event_type == "deprecation":
            return self._prefix_message("Deprecation warning", message or raw)

        if event_type == "timeout":
            return "Timeout or deadline exceeded"

        if event_type == "connection":
            if "EADDRINUSE" in raw or "address already in use" in raw.lower():
                return "Port already in use"
            return "Connection failure"

        if event_type == "warning":
            return self._prefix_message("Warning", message or raw)

        if message:
            return self._prefix_message(event_type.replace("_", " ").title(), message)

        return self._prefix_message(event_type.replace("_", " ").title(), raw)

    def _issue_why(
        self,
        event_type: str,
        table: str,
        message: str,
        raw: str,
        bullet_mode: str = "",
    ) -> str:
        if event_type == "eager_load":
            assoc = self._association_summary(message, limit=3)
            if bullet_mode == "avoid":
                if table and assoc:
                    return (
                        f"Bullet reports `{table}` is eager loading `{assoc}` but not using it "
                        "in the observed code path."
                    )
                return "Bullet flagged eager loading that appears to be unnecessary for this code path."
            if table and assoc:
                return (
                    f"Repeated access to `{table}` is loading `{assoc}` lazily, "
                    "which usually means an N+1 query path."
                )
            return "Bullet flagged a repeated association load that is likely causing N+1 queries."

        if event_type == "deprecation":
            return "The current code path is calling an API that is marked for removal or replacement."

        if event_type == "timeout":
            return "A dependency, network call, or request path exceeded its allowed wait time."

        if event_type == "connection":
            return "The app could not open or keep a required network/socket connection."

        if event_type in {"error", "exception", "panic", "oom", "unhandled", "traceback"}:
            return "The same failure signature appeared multiple times in this run and is worth fixing at the source."

        if event_type == "concurrency":
            return "The runtime detected overlapping access or a deadlock condition."

        if event_type == "warning":
            return "The same warning fingerprint repeated in the current session."

        return f"This {event_type.replace('_', ' ')} event repeated enough to be grouped as one issue."

    def _issue_suggestion(
        self,
        event_type: str,
        table: str,
        message: str,
        raw: str,
        bullet_mode: str = "",
    ) -> Any:
        if event_type == "eager_load":
            assoc = self._association_summary(message, limit=2)
            if bullet_mode == "avoid":
                if table and assoc:
                    target = f"`{table}` -> `{assoc}`"
                elif table:
                    target = f"`{table}`"
                else:
                    target = "the eager-loaded association"
                return (
                    f"Remove the unnecessary `includes`, `preload`, or `eager_load` for {target}, or keep it only if the association is actually used in this response path.",
                    "high",
                    "low",
                )

            if table and assoc:
                target = f"the query loading `{table}` -> `{assoc}`"
            elif table:
                target = f"the query loading `{table}`"
            else:
                target = "the parent query"
            return (
                f"Preload the association for {target} using `includes`, `preload`, or `eager_load` close to the query that fetches the records.",
                "high",
                "low",
            )

        if event_type == "deprecation":
            return (
                "Replace the deprecated API or config with the supported alternative named in the warning before the next dependency upgrade.",
                "medium",
                "low",
            )

        if event_type == "timeout":
            return (
                "Check the slow dependency first, then raise the relevant local timeout only if the wait is expected and safe.",
                "medium",
                "medium",
            )

        if event_type == "connection":
            if "EADDRINUSE" in raw or "address already in use" in raw.lower():
                return (
                    "Free the conflicting port or move the service to an unused port in local config.",
                    "high",
                    "low",
                )
            return (
                "Verify the target host, port, and credentials, then confirm the dependency is running before retrying.",
                "medium",
                "medium",
            )

        return (None, None, None)

    def _issue_autofix(
        self,
        event_type: str,
        table: str,
        message: str,
        raw: str,
        bullet_mode: str,
        event: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if self._autofix_mode == "off":
            return None

        if event_type == "eager_load" and bullet_mode == "avoid":
            return self._bullet_remove_autofix(table, message, event)
        if event_type == "connection":
            return self._port_collision_autofix(raw)

        return None

    def _bullet_remove_autofix(
        self,
        table: str,
        message: str,
        event: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        query_hint = self._clean_text(event.get("bullet_query_hint"))
        if not query_hint:
            return None

        assoc = self._association_summary(message, limit=2)
        target = f"{table} -> {assoc}" if table and assoc else table or "this query path"
        plan = {
            "rule_id": "bullet_remove_exact_hint",
            "search": query_hint,
            "replacement": "",
            "table": table,
            "association": assoc,
            "target": target,
            "request_id": event.get("request_id"),
            "callstack": list(event.get("bullet_callstack") or []),
        }

        if not query_hint.startswith((".includes(", ".preload(", ".eager_load(")):
            return {
                **plan,
                "status": "unavailable",
                "auto_apply": False,
                "reason": "Bullet suggested removing an eager-loading hint, but it was not a direct includes/preload/eager_load snippet.",
            }

        target_path = self._resolve_callstack_path(event.get("bullet_callstack"))
        if target_path is None:
            return {
                **plan,
                "status": "unavailable",
                "auto_apply": False,
                "reason": "Bullet did not expose a source file in the captured call stack, so devdoctor cannot build a safe patch automatically.",
            }

        try:
            source = target_path.read_text(encoding="utf-8")
        except OSError as exc:
            return {
                **plan,
                "status": "unavailable",
                "auto_apply": False,
                "file": str(target_path),
                "reason": f"devdoctor could not read {target_path.name}: {exc}",
            }

        match_count = source.count(query_hint)

        if match_count != 1:
            reason = (
                f"Found {match_count} exact matches for {query_hint} in {target_path.name}; "
                "auto-apply only runs when there is exactly one unambiguous match."
            )
            return {
                **plan,
                "status": "unavailable",
                "auto_apply": False,
                "file": str(target_path),
                "reason": reason,
            }

        updated = source.replace(query_hint, "", 1)
        patch_preview = self._build_patch_preview(target_path, source, updated)
        return {
            **plan,
            "status": "available",
            "auto_apply": True,
            "file": str(target_path),
            "summary": f"Remove {query_hint} from {target_path.name} for {target}.",
            "patch_preview": patch_preview,
        }

    def _port_collision_autofix(self, raw: str) -> Optional[Dict[str, Any]]:
        match = _PORT_COLLISION_RE.search(raw)
        if not match:
            return None

        current_port = int(match.group("port"))
        next_port = self._next_available_port(current_port + 1)
        if next_port is None:
            return {
                "rule_id": "port_collision_bump",
                "status": "unavailable",
                "auto_apply": False,
                "reason": f"Could not find a free local port after {current_port}.",
            }

        matches = self._find_port_config_matches(current_port, next_port)
        if len(matches) != 1:
            reason = (
                f"Found {len(matches)} candidate config locations for port {current_port}; "
                "auto-apply only runs when there is exactly one unambiguous match."
            )
            return {
                "rule_id": "port_collision_bump",
                "status": "unavailable",
                "auto_apply": False,
                "current_port": current_port,
                "next_port": next_port,
                "reason": reason,
            }

        match_info = matches[0]
        return {
            "rule_id": "port_collision_bump",
            "status": "available",
            "auto_apply": True,
            "file": str(match_info["file"]),
            "search": match_info["search"],
            "replacement": match_info["replacement"],
            "current_port": current_port,
            "next_port": next_port,
            "summary": f"Bump local port from {current_port} to {next_port} in {Path(match_info['file']).name}.",
            "patch_preview": match_info["patch_preview"],
        }

    def _find_port_config_matches(self, current_port: int, next_port: int) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        for path in self._iter_port_candidate_files():
            try:
                source = path.read_text(encoding="utf-8")
            except OSError:
                continue

            for pattern in self._port_line_patterns(current_port):
                regex_match = pattern.search(source)
                if regex_match is None:
                    continue
                search = regex_match.group("search")
                replacement = search.replace(str(current_port), str(next_port), 1)
                updated = source.replace(search, replacement, 1)
                matches.append(
                    {
                        "file": str(path.resolve()),
                        "search": search,
                        "replacement": replacement,
                        "patch_preview": self._build_patch_preview(path, source, updated),
                    }
                )
        unique: Dict[str, Dict[str, Any]] = {}
        for match in matches:
            unique[f'{match["file"]}|{match["search"]}'] = match
        return list(unique.values())

    def _normalize_association(self, message: str) -> str:
        cleaned = message.strip()
        cleaned = cleaned.strip("[]")
        cleaned = cleaned.replace(":", "")
        cleaned = cleaned.replace(",", ", ")
        return _WS_RE.sub(" ", cleaned).strip()

    def _association_summary(self, message: str, limit: int) -> str:
        normalized = self._normalize_association(message)
        if not normalized:
            return ""

        items = [item.strip() for item in normalized.split(",") if item.strip()]
        if len(items) <= limit:
            return ", ".join(items)
        return f'{", ".join(items[:limit])} +{len(items) - limit} more'

    def _prefix_message(self, prefix: str, message: str) -> str:
        trimmed = _WS_RE.sub(" ", message).strip()
        if not trimmed:
            return prefix
        return f"{prefix}: {trimmed[:96]}"

    def _resolve_callstack_path(self, frames: Any) -> Optional[Path]:
        if not isinstance(frames, list):
            return None

        for frame in frames:
            raw = self._clean_text(frame)
            if not raw:
                continue

            path_part = raw.split(":", 1)[0]
            candidates = [Path(path_part)]
            if not Path(path_part).is_absolute():
                candidates.append(self._project_root / path_part)

            for candidate in candidates:
                if candidate.is_file():
                    return candidate.resolve()

        return None

    def _build_patch_preview(self, path: Path, before: str, after: str) -> str:
        diff = difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=str(path),
            tofile=str(path),
            lineterm="",
        )
        return "\n".join(diff)

    def _port_line_patterns(self, current_port: int) -> List[re.Pattern[str]]:
        port = re.escape(str(current_port))
        return [
            re.compile(rf"(?P<search>\bPORT=(?P<port>{port}))"),
            re.compile(rf'(?P<search>"port"\s*:\s*(?P<port>{port}))', re.IGNORECASE),
            re.compile(rf"(?P<search>\bport\s*[:=]\s*(?P<port>{port}))", re.IGNORECASE),
            re.compile(rf"(?P<search>\bapp\.listen\(\s*(?P<port>{port})\b)", re.IGNORECASE),
            re.compile(rf'(?P<search>ListenAndServe\(\s*"[:]?((?P<port>{port}))")', re.IGNORECASE),
            re.compile(rf"(?P<search>\bport\s*=\s*(?P<port>{port}))", re.IGNORECASE),
        ]

    def _iter_port_candidate_files(self) -> Iterable[Path]:
        preferred = [
            self._project_root / ".env",
            self._project_root / ".env.local",
            self._project_root / ".env.development",
            self._project_root / "docker-compose.yml",
            self._project_root / "docker-compose.yaml",
            self._project_root / "compose.yml",
            self._project_root / "compose.yaml",
            self._project_root / "package.json",
        ]
        seen = set()
        for path in preferred:
            if path.is_file():
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    yield resolved

        for path in self._project_root.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix not in _PORT_SEARCH_SUFFIXES and path.name.lower() != "package.json":
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield resolved

    def _next_available_port(self, start: int) -> Optional[int]:
        for port in range(start, min(start + 50, 65536)):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind(("127.0.0.1", port))
                except OSError:
                    continue
                return port
        return start if 0 < start < 65536 else None
