"""Parser engine: JSON-first, regex fallback."""

import json
import re
from typing import Dict, Any, Optional

from .patterns import DEFAULT_PATTERNS


class ParserEngine:
    def __init__(self, patterns: Optional[Dict[str, str]] = None):
        self._patterns = {
            name: re.compile(pattern)
            for name, pattern in (patterns or DEFAULT_PATTERNS).items()
        }

    def parse(self, line: str) -> Dict[str, Any]:
        """Parse a raw log line into a normalized event."""
        stripped = line.rstrip("\n")

        # Try JSON first
        json_event = self._try_json(stripped)
        if json_event is not None:
            return json_event

        # Fallback to regex
        return self._try_regex(stripped)

    def _try_json(self, line: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                return None
            return {
                "type": data.get("level", data.get("type", "log")),
                "message": data.get("message", data.get("msg")),
                "duration": str(data["duration"]) if "duration" in data else None,
                "table": data.get("table"),
                "raw": line,
            }
        except (json.JSONDecodeError, ValueError):
            return None

    def _try_regex(self, line: str) -> Dict[str, Any]:
        for event_type, pattern in self._patterns.items():
            m = pattern.search(line)
            if m:
                groups = m.groupdict()
                return {
                    "type": event_type,
                    "message": groups.get("message"),
                    "duration": groups.get("duration"),
                    "table": groups.get("table"),
                    "raw": line,
                }
        return {
            "type": "log",
            "message": None,
            "duration": None,
            "table": None,
            "raw": line,
        }
