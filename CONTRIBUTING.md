# Developer Documentation

This document is for contributors and anyone who wants to understand how devdoctor works internally, extend it, or build on top of it.

---

## Table of contents

1. [Architecture overview](#1-architecture-overview)
2. [Data flow](#2-data-flow)
3. [Module reference](#3-module-reference)
4. [How the parser works](#4-how-the-parser-works)
5. [How the HTML writer works](#5-how-the-html-writer-works)
6. [How snapshots work](#6-how-snapshots-work)
7. [Thread safety model](#7-thread-safety-model)
8. [Adding a new event type](#8-adding-a-new-event-type)
9. [Adding a new pattern](#9-adding-a-new-pattern)
10. [Code review notes (v1)](#10-code-review-notes-v1)
11. [Setting up a dev environment](#11-setting-up-a-dev-environment)
12. [Release checklist](#12-release-checklist)

---

## 1. Architecture overview

devdoctor is built around a single concept: **a line processing pipeline**.

```
Input source (run | watch)
    │
    ▼
Stream processor        ← reads raw bytes, decodes to str
    │
    ▼
ParserEngine.parse()    ← JSON-first, regex fallback
    │
    ▼
Normalised event dict   ← {type, message, duration, table, raw}
    │
    ├──► SnapshotManager.add_event()   ← in-memory list, flushed on exit
    └──► HtmlWriter.add_event()        ← optional, throttled disk write
```

Every component is independent. The parser does not know about snapshots. The HTML writer does not know about the runner. This makes each piece testable and replaceable.

---

## 2. Data flow

### Run mode

```
subprocess (stdout pipe)  ──┐
                             ├── Queue[str] ──► main thread ──► parse ──► snapshot / html
subprocess (stderr pipe)  ──┘
```

Two daemon threads read the subprocess pipes concurrently. They write directly to `sys.stdout` for real-time output, then push each decoded line onto a shared `queue.Queue`. The main thread is the **only thread** that calls `snapshot.add_event()` and `html_writer.add_event()` — no locks needed.

### Watch mode

Single-threaded. The main thread polls `file.readline()` every 100 ms. When a line arrives it is immediately written to stdout, parsed, and handed to snapshot + html writer. No queue needed.

---

## 3. Module reference

### `devdoctor/cli.py`

Entry point. Owns:
- `argparse` setup including all help text and epilogs
- Loading config, constructing `ParserEngine`, `SnapshotManager`, and optional `HtmlWriter`
- Dispatching to `runner.run_command` or `watcher.watch_file`

**Key function:** `main()` — called by the `devdoctor` console script.

---

### `devdoctor/runner.py`

Executes a subprocess and streams its output.

**Key function:** `run_command(command, snapshot, parser, html_writer=None) -> int`

- Spawns two daemon threads (`_stream`) that read stdout and stderr pipes
- Lines are written to stdout immediately (real-time) and pushed to a `Queue`
- Main thread drains the queue, parses each line, sends to snapshot and html_writer
- Returns the subprocess exit code

**Design note:** `_SENTINEL = None` is used to signal pipe EOF from each thread. The main loop counts two sentinels before exiting.

---

### `devdoctor/watcher.py`

Tails a log file continuously.

**Key function:** `watch_file(log_path, snapshot, parser, html_writer=None) -> int`

Constants:
```python
STALE_THRESHOLD_SECONDS = 5    # warn if no new lines for this long
POLL_INTERVAL = 0.1            # seconds between readline() attempts
```

**Log rotation detection:** On every idle poll, `_inode(path)` is compared to the inode captured when the file was opened. If they differ, the file was rotated — the handle is closed and reopened at position 0.

---

### `devdoctor/parser/engine.py`

**Class:** `ParserEngine(patterns: dict | None)`

- Compiles all regex patterns on `__init__` — pattern compilation happens once, never on hot path
- `parse(line) -> dict` tries `_try_json` first, then `_try_regex`, finally returns a bare `log` event
- Normalised event always has all five keys: `type`, `message`, `duration`, `table`, `raw`

**JSON detection:** A line is treated as JSON if `json.loads()` succeeds and returns a `dict`. Field mapping:

| JSON key | Event field | Notes |
|----------|-------------|-------|
| `level` or `type` | `type` | falls back to `"log"` |
| `message` or `msg` | `message` | |
| `duration` | `duration` | cast to `str` |
| `table` | `table` | |

---

### `devdoctor/parser/patterns.py`

Single dict `DEFAULT_PATTERNS`. All patterns must use **named capture groups**:

```python
r"Completed \d+ .* in (?P<duration>\d+)ms"
#                         ^^^^^^^^^^^^ named group maps to event field
```

---

### `devdoctor/config/loader.py`

`load_config(config_path="devdoctor.toml") -> dict`

- If no config file: returns `{"patterns": dict(DEFAULT_PATTERNS)}`
- If file exists: parses with `tomllib` (Python 3.11+) or `tomli` (3.9–3.10)
- Merges `[patterns]` section over defaults — only listed keys are overridden
- On any parse error: prints a warning, returns defaults (never crashes)

---

### `devdoctor/snapshot/manager.py`

**Class:** `SnapshotManager`

- Registers `SIGINT` and `SIGTERM` handlers on `__init__`
- `add_event(event)` — appends to `self._events` (called from main thread only)
- `save()` — atomically writes `session-<ts>.json`; idempotent (`_saved` flag prevents double-write)
- Atomic write: `json.dump` → `.tmp` file → `os.replace()` to final path

---

### `devdoctor/output/html_writer.py`

**Class:** `HtmlWriter(output_dir: Path, project_id: str)`

- Creates `output-<ts>.html` immediately with an empty "waiting" state
- `add_event(event)` — enriches event with `_ts` (wall-clock HH:MM:SS), appends to list, flushes to disk at most once per second (`_FLUSH_INTERVAL = 1.0`)
- `close()` — writes final page with `final=True`: removes `<meta http-equiv="refresh">`, changes pill from LIVE → DONE
- All writes are atomic (`.tmp` + `os.replace`)

**Scroll preservation:** The HTML page includes inline JS that saves `document.documentElement.scrollTop` to `sessionStorage` before each meta-refresh reload, and restores it on `DOMContentLoaded`.

---

### `devdoctor/utils/project.py`

Four small functions:

| Function | Returns |
|----------|---------|
| `get_project_name()` | `Path.cwd().name` |
| `get_project_hash()` | MD5 of full CWD path, first 8 hex chars |
| `get_project_id()` | `"<name>-<hash>"` |
| `get_sessions_dir()` | `~/.devdoctor/projects/<id>/sessions/` (created if absent) |
| `get_output_dir(override)` | `~/.devdoctor/projects/<id>/output/` or custom path |

---

## 4. How the parser works

```
raw line
  │
  ├─► json.loads() ──► success + is dict ──► map to normalised event
  │                          │
  │                     failure / not dict
  │                          │
  └─► iterate compiled patterns ──► first match ──► extract named groups
                                          │
                                     no match
                                          │
                                    {type: "log", all fields: None}
```

The regex loop is ordered by dict insertion order (Python 3.7+). The first matching pattern wins. If you need priority control, put your most specific patterns first in `devdoctor.toml`.

---

## 5. How the HTML writer works

The HTML file is fully self-contained — no external JS or CSS dependencies. It is regenerated on every flush from a Python f-string template.

**Rendering pipeline:**

```
self._events  (list of enriched dicts)
    │
    ▼
_render(final)
    ├── compute stats (error/latency/query/total counts)
    ├── choose status_label (LIVE | DONE) and status_color
    ├── build refresh_tag (empty string if final)
    └── _render_rows()
          └── reversed(self._events) → one <tr> per event
```

**Why reversed?** Newest events appear at the top of the table, so you don't need to scroll down to see what just happened.

**Type → style mapping** (`_TYPE_META`):

```python
{
    "error":   bar="#ff5f5f", badge_bg="#c0392b"
    "latency": bar="#ffd700", badge_bg="#7d6608"
    "query":   bar="#5fafff", badge_bg="#1a5276"
    "log":     bar="#3d4450", badge_bg="#2d333b"
}
```

Unknown event types fall through to the `log` style.

---

## 6. How snapshots work

```
SnapshotManager.__init__()
    └── registers SIGINT + SIGTERM handlers

On Ctrl+C or SIGTERM:
    _handle_signal()
        └── save()
                └── json.dump to .tmp
                        └── os.replace(.tmp → session-<ts>.json)
                                └── sys.exit(0)

On normal exit (run mode):
    main() calls snapshot.save() explicitly
    (save() is idempotent — _saved flag prevents double write)
```

**Why atomic write?** A Ctrl+C arrives at any moment. Without `.tmp` + `os.replace`, a signal during `json.dump` would leave a partial file that looks valid but isn't.

---

## 7. Thread safety model

| Thread | What it does | Shared state it touches |
|--------|-------------|------------------------|
| stdout reader | Reads proc.stdout, writes to sys.stdout, puts to Queue | sys.stdout (GIL-safe), Queue (thread-safe) |
| stderr reader | Reads proc.stderr, writes to sys.stdout, puts to Queue | sys.stdout (GIL-safe), Queue (thread-safe) |
| main | Drains Queue, calls parse/snapshot/html_writer | `_events` list — **sole writer** |

`sys.stdout.write` is safe from multiple threads in CPython because the GIL serialises the underlying C write call. The `Queue` is Python's thread-safe FIFO. `_events` is never touched by the reader threads.

In watch mode there is only one thread — no concurrency at all.

---

## 8. Adding a new event type

Say you want to detect cache hits: `CACHE HIT: users#42 (0.3ms)`.

**Step 1 — Add the pattern** (`parser/patterns.py`):

```python
DEFAULT_PATTERNS = {
    "latency": r"Completed \d+ .* in (?P<duration>\d+)ms",
    "error":   r"(ERROR|FATAL): (?P<message>.*)",
    "query":   r"SELECT .* FROM (?P<table>\w+)",
    "cache":   r"CACHE HIT: (?P<table>\w+)#\d+ \((?P<duration>[\d.]+)ms\)",  # new
}
```

**Step 2 — Add HTML styling** (`output/html_writer.py`):

```python
_TYPE_META = {
    ...
    "cache": {"bar": "#50fa7b", "badge_bg": "#1e4a2e", "badge_fg": "#50fa7b", "label": "CACHE"},
}
```

**Step 3 — Done.** The parser, snapshot, and HTML table all handle arbitrary `type` values.

---

## 9. Adding a new pattern

Users can override patterns in `devdoctor.toml` without touching the code:

```toml
[patterns]
latency = 'Request took (?P<duration>\d+)ms'
```

To add a completely new named type from config, the user adds it with any name:

```toml
[patterns]
deploy = 'Deploying (?P<message>[^\s]+) to production'
```

The event `type` will be `"deploy"`, and it will render with the `log` fallback style in HTML (since no custom style is defined). In v2 this can be made configurable.

---

## 10. Code review notes (v1)

Issues identified and their status:

| # | File | Issue | Status |
|---|------|-------|--------|
| 1 | `runner.py` | Two threads mutating `_events` directly | Fixed — queue + main-thread-only mutation |
| 2 | `snapshot/manager.py` | Direct `write_text` — partial file on crash | Fixed — `.tmp` + `os.replace` |
| 3 | `watcher.py` | File handle became stale on log rotation | Fixed — inode tracking + reopen |
| 4 | `parser/engine.py` | Patterns compiled on every `parse()` call | Fixed — compiled in `__init__` |
| 5 | `utils/project.py` | `str \| None` union syntax (requires Python 3.10) | Fixed — changed to `Optional[str]` |
| 6 | `snapshot/manager.py` | Previous SIGINT handler not chained | Known — acceptable for a CLI tool; v2 should chain |
| 7 | `html_writer.py` | `_render()` is ~200 lines, hard to read | Known — works correctly; refactor in v2 |
| 8 | `config/loader.py` | Nested try/except for tomllib/tomli | Known — works correctly; simplifiable |
| 9 | All | No unit tests | Tracked — v2 priority |

---

## 11. Setting up a dev environment

```bash
git clone https://github.com/<user>/devdoctor.git
cd devdoctor

python3 -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"
```

Add dev dependencies to `pyproject.toml` when tests are added:

```toml
[project.optional-dependencies]
dev = ["pytest", "pytest-cov"]
```

**Manual smoke test:**

```bash
devdoctor run -- python3 -c "
print('Completed 200 OK in 142ms')
print('ERROR: test error')
print('SELECT id FROM users')
"
```

**Test watch mode:**

```bash
echo "" > /tmp/test.log
devdoctor watch /tmp/test.log &
echo "Completed 200 OK in 99ms" >> /tmp/test.log
echo "ERROR: disk full" >> /tmp/test.log
kill %1
```

---

## 12. Release checklist

1. Bump version in `devdoctor/__init__.py`
2. Update `pyproject.toml` version field
3. Commit: `git commit -m "chore: bump version to X.Y.Z"`
4. Tag: `git tag vX.Y.Z`
5. Build: `python -m build`
6. Publish: `twine upload dist/*`
7. Update Homebrew formula SHA256:
   ```bash
   curl -L https://github.com/<user>/devdoctor/archive/refs/tags/vX.Y.Z.tar.gz | sha256sum
   ```
8. Push tag: `git push origin vX.Y.Z`
