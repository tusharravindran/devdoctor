"""Parser engine: JSON-first, regex fallback, with multiline Bullet grouping."""

import json
import re
from typing import Dict, Any, List, Optional

from .patterns import DEFAULT_PATTERNS

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_REQUEST_ID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}"
    r"-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_BULLET_HEADER_RE = re.compile(r"(?P<mode>AVOID|USE) eager loading detected")
_BULLET_TARGET_RE = re.compile(r"\s+(?P<table>\w+) => \[(?P<message>[^\]]*)\]")
_BULLET_ADD_RE = re.compile(r"\s*Add to your query:\s*(?P<hint>.+)")
_BULLET_REMOVE_RE = re.compile(r"\s*Remove from your query:\s*(?P<hint>.+)")
_BULLET_CALLSTACK_RE = re.compile(r"\s*Call stack")
_JSON_LEVEL_MAP = {
    "warn": "warning",
    "warning": "warning",
    "fatal": "error",
    "critical": "error",
    "err": "error",
    "error": "error",
    "info": "log",
    "debug": "log",
}


class ParserEngine:
    def __init__(self, patterns: Optional[Dict[str, str]] = None):
        self._patterns = {
            name: re.compile(pattern)
            for name, pattern in (patterns or DEFAULT_PATTERNS).items()
        }
        self._pending_bullet: Optional[Dict[str, Any]] = None

    def parse(self, line: str) -> List[Dict[str, Any]]:
        """Parse a raw log line into zero or more normalized events."""
        raw = line.rstrip("\n")
        clean = self._strip_ansi(raw)
        emitted: List[Dict[str, Any]] = []

        if self._pending_bullet is not None:
            if self._is_bullet_header(clean):
                emitted.append(self._finalize_bullet())
                self._start_bullet(clean, raw)
                return emitted

            if self._is_bullet_continuation(clean):
                self._consume_bullet_line(clean, raw)
                return emitted

            emitted.append(self._finalize_bullet())

        if self._is_bullet_header(clean):
            self._start_bullet(clean, raw)
            return emitted

        # Try JSON first
        json_event = self._try_json(clean, raw)
        if json_event is not None:
            emitted.append(json_event)
            return emitted

        # Fallback to regex
        emitted.append(self._try_regex(clean, raw))
        return emitted

    def flush(self) -> List[Dict[str, Any]]:
        """Flush any pending multiline state into finalized events."""
        if self._pending_bullet is None:
            return []
        return [self._finalize_bullet()]

    def _strip_ansi(self, line: str) -> str:
        return _ANSI_RE.sub("", line)

    def _try_json(self, line: str, raw: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                return None
            raw_type = str(data.get("level", data.get("type", "log"))).strip().lower()
            return {
                "type": _JSON_LEVEL_MAP.get(raw_type, raw_type or "log"),
                "message": data.get("message", data.get("msg")),
                "duration": str(data["duration"]) if "duration" in data else None,
                "table": data.get("table"),
                "raw": raw,
                "request_id": self._extract_request_id(raw),
            }
        except (json.JSONDecodeError, ValueError):
            return None

    def _try_regex(self, line: str, raw: str) -> Dict[str, Any]:
        for event_type, pattern in self._patterns.items():
            m = pattern.search(line)
            if m:
                groups = m.groupdict()
                return {
                    "type": event_type,
                    "message": groups.get("message"),
                    "duration": groups.get("duration"),
                    "table": groups.get("table"),
                    "raw": raw,
                    "request_id": self._extract_request_id(raw),
                }
        return {
            "type": "log",
            "message": None,
            "duration": None,
            "table": None,
            "raw": raw,
            "request_id": self._extract_request_id(raw),
        }

    def _is_bullet_header(self, line: str) -> bool:
        return _BULLET_HEADER_RE.search(line) is not None

    def _is_bullet_continuation(self, line: str) -> bool:
        if not line.strip():
            return True
        if _BULLET_TARGET_RE.search(line):
            return True
        if _BULLET_ADD_RE.search(line) or _BULLET_REMOVE_RE.search(line):
            return True
        if _BULLET_CALLSTACK_RE.search(line):
            return True
        return bool(
            self._pending_bullet
            and self._pending_bullet.get("in_call_stack")
            and (line.startswith("  ") or line.startswith("\t"))
        )

    def _start_bullet(self, line: str, raw: str) -> None:
        header = _BULLET_HEADER_RE.search(line)
        mode = header.group("mode").lower() if header else "use"
        self._pending_bullet = {
            "mode": mode,
            "raw_lines": [raw],
            "targets": [],
            "query_hints": [],
            "callstack": [],
            "in_call_stack": False,
            "request_id": self._extract_request_id(raw),
        }

    def _consume_bullet_line(self, line: str, raw: str) -> None:
        if self._pending_bullet is None:
            return

        self._pending_bullet["raw_lines"].append(raw)
        if not self._pending_bullet.get("request_id"):
            self._pending_bullet["request_id"] = self._extract_request_id(raw)

        target = _BULLET_TARGET_RE.search(line)
        if target:
            self._pending_bullet["targets"].append(
                {
                    "table": target.group("table"),
                    "message": target.group("message").strip(),
                }
            )
            return

        add_hint = _BULLET_ADD_RE.search(line)
        if add_hint:
            self._pending_bullet["query_hints"].append(add_hint.group("hint").strip())
            return

        remove_hint = _BULLET_REMOVE_RE.search(line)
        if remove_hint:
            self._pending_bullet["query_hints"].append(remove_hint.group("hint").strip())
            return

        if _BULLET_CALLSTACK_RE.search(line):
            self._pending_bullet["in_call_stack"] = True
            return

        if self._pending_bullet.get("in_call_stack") and line.strip():
            self._pending_bullet["callstack"].append(line.strip())

    def _finalize_bullet(self) -> Dict[str, Any]:
        pending = self._pending_bullet or {}
        self._pending_bullet = None

        targets = pending.get("targets") or []
        table = targets[0]["table"] if targets else None
        message = self._summarize_bullet_targets(targets)
        return {
            "type": "eager_load",
            "message": message,
            "duration": None,
            "table": table,
            "raw": "\n".join(pending.get("raw_lines") or []),
            "request_id": pending.get("request_id"),
            "bullet_mode": pending.get("mode"),
            "bullet_targets": targets,
            "bullet_query_hint": " | ".join(pending.get("query_hints") or []),
            "bullet_callstack": pending.get("callstack") or [],
        }

    def _extract_request_id(self, line: str) -> Optional[str]:
        match = _REQUEST_ID_RE.search(line)
        return match.group(0) if match else None

    def _summarize_bullet_targets(self, targets: List[Dict[str, str]]) -> Optional[str]:
        if not targets:
            return None

        if len(targets) == 1:
            return targets[0].get("message") or None

        tables = {target.get("table") for target in targets if target.get("table")}
        if len(tables) == 1:
            messages = [target.get("message", "").strip() for target in targets if target.get("message")]
            return ", ".join(messages) if messages else None

        parts = []
        for target in targets:
            target_table = target.get("table")
            target_message = target.get("message")
            if target_table and target_message:
                parts.append(f"{target_table}: {target_message}")
            elif target_table:
                parts.append(target_table)
        return " | ".join(parts) if parts else None
