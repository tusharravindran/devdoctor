"""Watch mode: tail a log file and stream lines through pipeline."""

import os
import sys
import time
from pathlib import Path

from .parser.engine import ParserEngine
from .snapshot.manager import SnapshotManager

STALE_THRESHOLD_SECONDS = 5
POLL_INTERVAL = 0.1


def _inode(path: Path) -> int:
    """Return the inode of path, or -1 if it no longer exists."""
    try:
        return path.stat().st_ino
    except FileNotFoundError:
        return -1


def watch_file(
    log_path: str,
    snapshot: SnapshotManager,
    parser: ParserEngine,
    html_writer=None,   # optional HtmlWriter
) -> int:
    path = Path(log_path)

    if not path.exists():
        print(f"[devdoctor] Error: log file not found: {log_path}", file=sys.stderr)
        return 1

    print(f"[devdoctor] Watching: {path.resolve()}", flush=True)
    print("[devdoctor] Press Ctrl+C to stop\n", flush=True)

    current_inode = _inode(path)
    last_activity = time.time()
    warned_stale = False

    f = open(path, "r", errors="replace")
    f.seek(0, 2)  # start at end — tail new content only

    try:
        while True:
            line = f.readline()
            if line:
                sys.stdout.write(line)
                sys.stdout.flush()
                event = parser.parse(line)
                snapshot.add_event(event)
                if html_writer is not None:
                    html_writer.add_event(event)
                last_activity = time.time()
                warned_stale = False
            else:
                time.sleep(POLL_INTERVAL)

                # Stale warning
                if not warned_stale and (time.time() - last_activity) > STALE_THRESHOLD_SECONDS:
                    print(
                        f"[devdoctor] Warning: {path.name} has not been updated "
                        f"for {time.time() - last_activity:.0f}s",
                        flush=True,
                    )
                    warned_stale = True

                # File removed
                if not path.exists():
                    print(f"[devdoctor] Warning: {path.name} was removed.", flush=True)
                    break

                # Log rotation: inode changed — reopen the new file
                if _inode(path) != current_inode:
                    print(
                        f"[devdoctor] Log rotated — reopening {path.name}",
                        flush=True,
                    )
                    f.close()
                    f = open(path, "r", errors="replace")
                    current_inode = _inode(path)
                    last_activity = time.time()
                    warned_stale = False
    finally:
        f.close()
        if html_writer is not None:
            html_writer.close()

    return 0
