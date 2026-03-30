"""Watch mode: tail a log file and stream lines through pipeline."""

import sys
import time
from pathlib import Path

from .parser.engine import ParserEngine
from .snapshot.manager import SnapshotManager
from .utils import color

STALE_THRESHOLD_SECONDS = 5
POLL_INTERVAL = 0.1


def _inode(path: Path) -> int:
    """Return the inode of path, or -1 if it no longer exists."""
    try:
        return path.stat().st_ino
    except FileNotFoundError:
        return -1


def _publish_events(events, snapshot: SnapshotManager, html_writer=None, autofix_manager=None) -> None:
    for event in events:
        annotation = color.event_annotation(event)
        if annotation:
            print(annotation, flush=True)
        snapshot.add_event(event)
        if html_writer is not None:
            html_writer.add_event(event)
        if autofix_manager is not None:
            autofix_manager.process_pending(html_writer=html_writer)


def watch_file(
    log_path: str,
    snapshot: SnapshotManager,
    parser: ParserEngine,
    html_writer=None,
    autofix_manager=None,
) -> int:
    path = Path(log_path)

    if not path.exists():
        print(color.error(f"log file not found: {log_path}"), file=sys.stderr, flush=True)
        return 1

    print(color.info(f"Watching  : {path.resolve()}"), flush=True)
    print(color.dim("Press Ctrl+C to stop\n"), flush=True)

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
                _publish_events(
                    parser.parse(line),
                    snapshot,
                    html_writer=html_writer,
                    autofix_manager=autofix_manager,
                )
                last_activity = time.time()
                warned_stale = False
            else:
                time.sleep(POLL_INTERVAL)

                elapsed = time.time() - last_activity

                # Stale warning — printed once per quiet spell
                if not warned_stale and elapsed > STALE_THRESHOLD_SECONDS:
                    print(
                        color.warn(
                            f"{path.name} has not been updated for {elapsed:.0f}s"
                        ),
                        flush=True,
                    )
                    warned_stale = True

                # File removed
                if not path.exists():
                    print(color.warn(f"{path.name} was removed."), flush=True)
                    break

                # Log rotation: inode changed → reopen the new file
                if _inode(path) != current_inode:
                    print(color.warn(f"Log rotated — reopening {path.name}"), flush=True)
                    f.close()
                    f = open(path, "r", errors="replace")
                    current_inode = _inode(path)
                    last_activity = time.time()
                    warned_stale = False
    finally:
        _publish_events(
            parser.flush(),
            snapshot,
            html_writer=html_writer,
            autofix_manager=autofix_manager,
        )
        f.close()

    return 0
