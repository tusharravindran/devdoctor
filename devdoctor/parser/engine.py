"""Parser engine: JSON-first, regex fallback."""

import json
import re
from typing import Dict, Any, Optional

from .patterns import DEFAULT_PATTERNS

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
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

    def parse(self, line: str) -> Dict[str, Any]:
        """Parse a raw log line into a normalized event."""
        raw = line.rstrip("\n")
        clean = self._strip_ansi(raw)

        # Try JSON first
        json_event = self._try_json(clean, raw)
        if json_event is not None:
            return json_event

        # Fallback to regex
        return self._try_regex(clean, raw)

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
                }
        return {
            "type": "log",
            "message": None,
            "duration": None,
            "table": None,
            "raw": raw,
        }
