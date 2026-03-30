"""Run mode: execute subprocess, stream stdout+stderr through pipeline."""

import subprocess
import sys
import threading
from queue import Queue
from typing import List, Optional

from .parser.engine import ParserEngine
from .snapshot.manager import SnapshotManager
from .utils import color

_SENTINEL = None


def _stream(pipe, queue: Queue, label: str) -> None:
    """Read lines from pipe and push them to the shared queue."""
    for raw_line in iter(pipe.readline, b""):
        line = raw_line.decode(errors="replace")
        queue.put(line)
    pipe.close()
    queue.put(_SENTINEL)


def run_command(
    command: List[str],
    snapshot: SnapshotManager,
    parser: ParserEngine,
    html_writer=None,
) -> int:
    if not command:
        print(color.error("no command provided."), file=sys.stderr, flush=True)
        return 1

    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print(color.error(f"command not found: {command[0]}"), file=sys.stderr, flush=True)
        return 1

    queue: Queue[Optional[str]] = Queue()

    t_out = threading.Thread(target=_stream, args=(proc.stdout, queue, "stdout"), daemon=True)
    t_err = threading.Thread(target=_stream, args=(proc.stderr, queue, "stderr"), daemon=True)
    t_out.start()
    t_err.start()

    # Main thread owns all snapshot + html mutations — no shared-state races.
    pipes_done = 0
    while pipes_done < 2:
        line = queue.get()
        if line is _SENTINEL:
            pipes_done += 1
        else:
            event = parser.parse(line)
            sys.stdout.write(line)
            sys.stdout.flush()
            annotation = color.event_annotation(event)
            if annotation:
                print(annotation, flush=True)
            snapshot.add_event(event)
            if html_writer is not None:
                html_writer.add_event(event)

    proc.wait()
    t_out.join()
    t_err.join()

    if html_writer is not None:
        html_writer.close()

    return proc.returncode
