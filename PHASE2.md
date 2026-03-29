# devdoctor v2 — Phase 2 Roadmap

This document defines the features, design decisions, and implementation plan for devdoctor v2.

v1 established the core pipeline: capture → parse → snapshot → HTML.
v2 transforms devdoctor from a passive observer into an **active diagnostics tool**.

---

## Guiding principles (unchanged from v1)

- No database, no server, no external services
- Zero-config to start
- Never block or modify original log output
- Everything lives in `~/.devdoctor/`
- Modular — each feature is independently usable

---

## Feature overview

| # | Feature | Command | Value |
|---|---------|---------|-------|
| 1 | Session browser | `devdoctor sessions` | Find and replay past sessions |
| 2 | Offline analysis | `devdoctor analyze` | Summarise a snapshot without re-running |
| 3 | Alert thresholds | `devdoctor.toml [alerts]` | Trigger warnings or exit codes on bad metrics |
| 4 | Multi-file watch | `devdoctor watch *.log` | Merge streams from multiple files |
| 5 | Live stats bar | `--stats` flag | Real-time error rate + latency in terminal |
| 6 | Session diff | `devdoctor diff` | Compare two snapshots ("what got worse?") |
| 7 | WebSocket server | `--serve` flag | Replace meta-refresh with live WS updates |
| 8 | Event filtering | `--filter` flag | Show / save only matching event types |
| 9 | Annotations | `devdoctor mark` | Insert timestamped markers into live sessions |
| 10 | Hooks | `devdoctor.toml [hooks]` | Shell commands triggered by event types |

---

## 1. Session browser — `devdoctor sessions`

Lets users find, view, and manage saved snapshots.

### Subcommands

```bash
devdoctor sessions list                   # list all sessions for current project
devdoctor sessions list --project myapp   # list sessions for a named project
devdoctor sessions show <session-id>      # print events from a session
devdoctor sessions clean --older 30d      # delete sessions older than 30 days
devdoctor sessions open <session-id>      # regenerate + open HTML from a snapshot
```

### `sessions list` output

```
Project: myapp-a1b2c3d4  (~/.devdoctor/projects/myapp-a1b2c3d4/)

  ID                      Date                 Events   Errors
  ─────────────────────────────────────────────────────────────
  20240301T140300Z        2024-03-01 14:03      847       12
  20240229T092100Z        2024-02-29 09:21      321        0
  20240228T161500Z        2024-02-28 16:15     1203       41
```

### `sessions show` output

```bash
devdoctor sessions show 20240301T140300Z
```

```
Session: 20240301T140300Z   Project: myapp-a1b2c3d4
─────────────────────────────────────────────────────
14:02:11  LATENCY  duration=142ms
14:02:15  ERROR    PG::ConnectionBad: could not connect to server
14:02:15  ERROR    ActiveRecord::NoDatabaseError
14:02:22  QUERY    table=users
...
```

### New files

```
devdoctor/
  sessions/
    browser.py    # list / show / clean commands
    renderer.py   # formats session data for terminal output
```

---

## 2. Offline analysis — `devdoctor analyze`

Runs analytics on a saved snapshot and prints a structured summary. No live process required.

```bash
devdoctor analyze                              # analyze most recent session
devdoctor analyze sessions/session-XYZ.json   # analyze a specific file
devdoctor analyze --format json               # machine-readable output
```

### Output

```
Session Analysis: session-20240301T140300Z
──────────────────────────────────────────
Total events     : 847
Duration         : 4m 12s

Event breakdown
  log      :  712  (84%)
  latency  :   98  (12%)
  error    :   27   (3%)
  query    :   10   (1%)

Latency (ms)
  min      :    8
  median   :   94
  p95      :  412
  max      : 1840
  over 500 :    6 requests

Top errors (by frequency)
  1.  PG::ConnectionBad: could not connect (18 occurrences)
  2.  NoMethodError: undefined method 'email' (7 occurrences)
  3.  ActionController::RoutingError (2 occurrences)

Top queried tables
  users (44),  orders (31),  products (12),  sessions (8)
```

### New files

```
devdoctor/
  analysis/
    __init__.py
    engine.py     # compute stats from event list
    formatter.py  # render stats to terminal or JSON
```

---

## 3. Alert thresholds — `devdoctor.toml [alerts]`

Configurable warnings and exit-code triggers. Useful for CI pipelines.

### Config

```toml
[alerts]
max_latency_ms     = 500       # warn when any single latency event exceeds this
max_error_rate     = 0.05      # warn when errors exceed 5% of total events
max_errors_per_min = 10        # warn when error frequency spikes
exit_on_alert      = false     # set true to exit with code 2 on threshold breach
```

### Terminal output

```
[devdoctor] ALERT  latency spike: 892ms (threshold: 500ms)
[devdoctor] ALERT  error rate: 8.3% over last 60s (threshold: 5%)
```

In HTML: alert rows are highlighted with a pulsing border and logged in a separate "Alerts" panel.

### New files

```
devdoctor/
  alerts/
    __init__.py
    checker.py    # evaluate thresholds against incoming events
    config.py     # parse [alerts] section from devdoctor.toml
```

### Integration with pipeline

`AlertChecker` sits in the main event loop alongside `snapshot.add_event`:

```python
event = parser.parse(line)
snapshot.add_event(event)
alert_checker.check(event)      # new
if html_writer:
    html_writer.add_event(event)
```

---

## 4. Multi-file watch — `devdoctor watch *.log`

Watch multiple log files simultaneously, merging all streams with a source label.

```bash
devdoctor watch log/*.log
devdoctor watch log/web.log log/worker.log log/cron.log
devdoctor watch --html log/*.log
```

### Terminal output

```
[web   ] Completed 200 OK in 142ms
[worker] ERROR: Sidekiq job failed — undefined method 'process'
[web   ] Completed 500 in 18ms
[cron  ] SELECT id FROM scheduled_jobs WHERE pending = true
```

### Design

Each file gets its own watcher thread. Lines are pushed onto a shared queue (same thread-safety model as `runner.py`) with a `source` field attached. The main thread drains and dispatches.

### Normalised event gains a new field

```json
{
  "type":     "error",
  "source":   "worker",
  "message":  "Sidekiq job failed",
  ...
}
```

### HTML

A source filter dropdown appears in the header: `All | web | worker | cron`.

---

## 5. Live stats bar — `--stats` flag

Print a one-line stats summary beneath the log stream, updated every second.

```bash
devdoctor watch --stats log/production.log
devdoctor run   --stats -- rails server
```

### Terminal output

```
  User Load (1.8ms)  SELECT "users".* FROM "users" WHERE id = 42
  Completed 200 OK in 88ms

  ─ events: 847  errors: 12 (1.4%)  latency p95: 204ms  queries: 44 ─
```

The stats line is drawn using ANSI escape codes to overwrite in place without scrolling the log output.

### New files

```
devdoctor/
  stats/
    __init__.py
    tracker.py    # rolling window counters (events, errors, latency buckets)
    renderer.py   # ANSI terminal stats line
```

---

## 6. Session diff — `devdoctor diff`

Compare two sessions and highlight regressions.

```bash
devdoctor diff 20240229T092100Z 20240301T140300Z
devdoctor diff --baseline 20240229T092100Z --current 20240301T140300Z
```

### Output

```
Diff: 20240229T092100Z → 20240301T140300Z
──────────────────────────────────────────
Events        :  321  →  847   (+164%)
Errors        :    0  →   27   (NEW)
Latency p95   :  98ms → 412ms  (+320%)  ← REGRESSION
Queries/req   :  1.2  →  3.8   (+217%)  ← REGRESSION

New error types (not in baseline):
  • PG::ConnectionBad: could not connect
  • ActiveRecord::NoDatabaseError

Tables with increased query volume:
  users: 12 → 44 (+267%)  orders: 0 → 31 (new)
```

### New files

```
devdoctor/
  diff/
    __init__.py
    engine.py     # compare two event lists, produce diff report
    formatter.py  # render diff to terminal
```

---

## 7. WebSocket live server — `--serve` flag

Replace meta-refresh with a proper WebSocket connection. No flicker, instant updates.

```bash
devdoctor watch --serve log/development.log
devdoctor run   --serve -- rails server
```

### Behaviour

- Starts a lightweight HTTP + WebSocket server on `localhost:7777` (configurable)
- Automatically opens the HTML in the default browser
- The HTML page holds a WebSocket connection; new events are pushed as JSON
- The browser appends rows to the table without a page reload

### Design constraints

- Must use **stdlib only** (`http.server`, `threading`, `socket`) — no `websockets` dependency
- The WebSocket handshake is ~50 lines; the protocol is simple enough for stdlib
- Server shuts down cleanly on SIGINT

### Config

```toml
[server]
port = 7777
open_browser = true
```

### New files

```
devdoctor/
  server/
    __init__.py
    ws_server.py   # minimal WebSocket server (RFC 6455 handshake + framing)
    handler.py     # HTTP handler that serves the HTML page
```

---

## 8. Event filtering — `--filter` flag

Show and record only specific event types.

```bash
devdoctor watch --filter error log/production.log
devdoctor watch --filter error,latency log/production.log
devdoctor run   --filter error -- rails server
```

### Behaviour

- Lines that don't match the filter are printed to stdout but **not** added to the snapshot or HTML
- `--filter` accepts a comma-separated list of event types
- `--filter error` is particularly useful in production: silent for normal traffic, loud for failures

---

## 9. Annotations — `devdoctor mark`

Insert a named marker into the active session while it is running.

```bash
# in a second terminal while devdoctor is watching:
devdoctor mark "deployed v1.2.3"
devdoctor mark "rolled back"
devdoctor mark --session 20240301T140300Z "scale-up completed"
```

### How it works

- `devdoctor mark` writes a special marker event to a sidecar file in the session directory:
  `~/.devdoctor/projects/<id>/sessions/<ts>.markers.jsonl`
- The active session (watcher/runner) polls the sidecar file and injects marker events into the stream
- In HTML: markers appear as a full-width divider row: `── deployed v1.2.3 ─ 14:03:22 ──`

### New event type

```json
{
  "type":    "marker",
  "message": "deployed v1.2.3",
  "raw":     "── deployed v1.2.3 ──"
}
```

---

## 10. Hooks — `devdoctor.toml [hooks]`

Run a shell command whenever a specific event type is detected.

```toml
[hooks]
on_error   = 'echo "[ALERT] {message}" | terminal-notifier'
on_latency = 'curl -s -X POST $SLACK_WEBHOOK -d "{\"text\":\"Slow request: {duration}ms\"}"'
```

### Substitution variables

| Variable | Value |
|----------|-------|
| `{type}` | Event type string |
| `{message}` | `message` field or empty |
| `{duration}` | `duration` field or empty |
| `{table}` | `table` field or empty |
| `{raw}` | Full raw log line |
| `{ts}` | Event timestamp |

### Design

- Hooks run in a background thread pool — they never block the main pipeline
- Failed hooks print a warning to stderr, never crash devdoctor
- Shell injection risk: variables are shell-quoted before substitution

### New files

```
devdoctor/
  hooks/
    __init__.py
    runner.py    # background thread pool, variable substitution, shell execution
    config.py    # parse [hooks] section from devdoctor.toml
```

---

## v2 project structure

```
devdoctor/
  cli.py
  runner.py
  watcher.py
  parser/
    engine.py
    patterns.py
  config/
    loader.py
  snapshot/
    manager.py
  output/
    html_writer.py
  utils/
    project.py
  # ── new in v2 ──────────────────────
  sessions/
    browser.py        # devdoctor sessions list/show/clean/open
    renderer.py
  analysis/
    engine.py         # devdoctor analyze
    formatter.py
  alerts/
    checker.py        # threshold evaluation
    config.py
  diff/
    engine.py         # devdoctor diff
    formatter.py
  stats/
    tracker.py        # rolling counters
    renderer.py       # ANSI stats bar
  server/
    ws_server.py      # devdoctor watch --serve
    handler.py
  hooks/
    runner.py         # devdoctor.toml [hooks]
    config.py
  annotations/
    writer.py         # devdoctor mark
    reader.py
```

---

## v2 CLI surface

```
devdoctor [--version] [--env ENV] <command>

Core commands (v1)
  run      Execute a command and stream its logs
  watch    Tail a log file (now supports multiple files and --serve)

New commands (v2)
  sessions  list | show | clean | open
  analyze   Summarise a saved snapshot
  diff      Compare two snapshots
  mark      Insert an annotation into an active session

New flags (v2)
  --filter  TYPE[,TYPE]   Only process matching event types
  --stats                 Show live stats bar in terminal
  --serve                 Serve HTML over WebSocket (no meta-refresh)
```

---

## v2 config additions (`devdoctor.toml`)

```toml
[patterns]
# same as v1

[alerts]
max_latency_ms     = 500
max_error_rate     = 0.05
max_errors_per_min = 10
exit_on_alert      = false

[hooks]
on_error   = 'notify-send "devdoctor" "Error: {message}"'
on_latency = ''

[server]
port         = 7777
open_browser = true

[sessions]
max_age_days = 90    # auto-clean sessions older than this
```

---

## Suggested build order

Each item is independently shippable as a patch or minor release.

```
v1.1  Event filtering (--filter)          — 1 day, self-contained
v1.2  Live stats bar (--stats)            — 2 days, no new dependencies
v1.3  Alert thresholds ([alerts])         — 2 days, extends config loader
v2.0  Session browser (sessions command)  — 3 days, new CLI subcommand
v2.1  Offline analysis (analyze command)  — 2 days, pure computation
v2.2  Session diff (diff command)         — 2 days, depends on analysis engine
v2.3  Multi-file watch                    — 3 days, threading extension
v2.4  Annotations (mark command)          — 2 days, sidecar file protocol
v2.5  Hooks ([hooks])                     — 2 days, thread pool
v2.6  WebSocket server (--serve)          — 4 days, most complex
```

---

## What v2 explicitly does NOT add

These are intentionally out of scope to keep devdoctor's dependency footprint at zero:

- No SQL query execution or DB connection
- No cloud integrations (Datadog, PagerDuty, Sentry)
- No plugin system with third-party packages
- No TUI (terminal UI framework like Rich or Textual) — only plain ANSI
- No AI/LLM summarisation — this is a recording and analysis tool, not an inference engine
