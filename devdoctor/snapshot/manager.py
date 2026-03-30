"""Snapshot manager: persists in-memory events on exit."""

import json
import os
import signal
import sys
from datetime import datetime, timezone
from typing import List, Dict, Any

from ..utils.project import get_sessions_dir
from ..utils import color


class SnapshotManager:
    def __init__(self):
        self._events: List[Dict[str, Any]] = []
        self._saved = False
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def add_event(self, event: Dict[str, Any]) -> None:
        self._events.append(event)

    def save(self) -> None:
        if self._saved or not self._events:
            return
        self._saved = True

        sessions_dir = get_sessions_dir()
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snapshot_path = sessions_dir / f"session-{ts}.json"
        tmp_path = str(snapshot_path) + ".tmp"

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "events": self._events,
        }

        # Atomic write: write to .tmp then rename so a crash mid-write
        # never leaves a partial snapshot file.
        with open(tmp_path, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, snapshot_path)

        print(color.success(f"Snapshot saved → {snapshot_path}"), flush=True)

    def _handle_signal(self, signum, frame):
        self.save()
        sys.exit(0)
