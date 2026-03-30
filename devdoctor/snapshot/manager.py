"""Snapshot manager: persists in-memory events on exit."""

import json
import os
import signal
import sys
from datetime import datetime, timezone
from typing import List, Dict, Any, Callable, Optional

from ..utils.project import get_sessions_dir
from ..utils import color


class SnapshotManager:
    def __init__(self, issue_tracker=None, request_tracker=None):
        self._events: List[Dict[str, Any]] = []
        self._issue_tracker = issue_tracker
        self._request_tracker = request_tracker
        self._finalizers: List[Callable[[], None]] = []
        self._saved = False
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def add_event(self, event: Dict[str, Any]) -> None:
        self._events.append(event)
        if self._issue_tracker is not None:
            self._issue_tracker.ingest(event)
        if self._request_tracker is not None:
            self._request_tracker.ingest(event)

    def register_finalizer(self, callback: Callable[[], None]) -> None:
        self._finalizers.append(callback)

    def save(self) -> None:
        if self._saved or not self._events:
            return
        self._saved = True

        for callback in self._finalizers:
            try:
                callback()
            except Exception:
                pass

        sessions_dir = get_sessions_dir()
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snapshot_path = sessions_dir / f"session-{ts}.json"
        tmp_path = str(snapshot_path) + ".tmp"

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "events": self._events,
        }
        if self._issue_tracker is not None:
            payload["issues"] = self._issue_tracker.snapshot_issues(final=True)
            payload["issue_counts"] = self._issue_tracker.tab_counts(final=True)
        if self._request_tracker is not None:
            payload["requests"] = self._request_tracker.snapshot_traces()
            payload["request_count"] = self._request_tracker.count()

        # Atomic write: write to .tmp then rename so a crash mid-write
        # never leaves a partial snapshot file.
        with open(tmp_path, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_path, snapshot_path)

        print(color.success(f"Snapshot saved → {snapshot_path}"), flush=True)

    def _handle_signal(self, signum, frame):
        self.save()
        sys.exit(0)


def load_latest_snapshot() -> Optional[Dict[str, Any]]:
    """Load the latest saved snapshot for the current project."""
    sessions_dir = get_sessions_dir()
    snapshots = sorted(sessions_dir.glob("session-*.json"))
    if not snapshots:
        return None

    latest_path = snapshots[-1]
    try:
        with open(latest_path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
