# devdoctor

**Real-time log diagnostics for backend developers.**

Stop staring at walls of text. devdoctor wraps any command or tails any log file, classifies every line as it arrives, and generates a browseable HTML report — all with zero configuration.

```
devdoctor run -- rails server
devdoctor watch --html log/development.log
```

---

## The problem it solves

When something breaks in production, you're doing this:

```
tail -f log/production.log | grep ERROR | ...
```

And you're losing context, losing history, and losing your mind.

devdoctor sits between your app and your terminal. It reads the same logs you already have, classifies each line in real time, keeps a full record of the session, and writes a shareable HTML report that updates live in your browser — without blocking or changing anything your app does.

---

## Install

```bash
pip install devdoctor
```

**From source:**

```bash
git clone https://github.com/tusharravindran/devdoctor.git
cd devdoctor
pip install -e .
```

**Homebrew:**

```bash
brew tap tusharravindran/devdoctor
brew install devdoctor
```

**Ubuntu / Debian third-party packaging:**

This repo now includes `.deb` and APT repository build tooling, and releases publish an unsigned third-party APT feed to the `apt` branch:

```bash
echo "deb [trusted=yes] https://raw.githubusercontent.com/tusharravindran/devdoctor/apt stable main" | sudo tee /etc/apt/sources.list.d/devdoctor.list
sudo apt update
sudo apt install devdoctor
```

To build that package feed locally:

```bash
python3 -m build --no-isolation
python3 scripts/build_deb.py --maintainer "DevDoctor Maintainers <noreply@github.com>"
python3 scripts/build_apt_repo.py --repo-dir apt-repo dist/*.deb
```

**Verify:**

```bash
devdoctor --version   # devdoctor 1.2.5
devdoctor --help
```

---

## 30-second quickstart

**Wrap a Rails server:**

```bash
devdoctor run -- rails server
```

**Tail a log file with live HTML:**

```bash
devdoctor watch --html log/development.log
```

That's it. Press `Ctrl+C` to stop. A JSON snapshot is saved automatically.

---

## Run mode

Wraps any command and streams both `stdout` and `stderr` through devdoctor in real time. Your original output is still printed, and devdoctor adds compact colored annotations for detected issues, warnings, latency, and queries.

```bash
devdoctor run -- <your command>
```

**Examples:**

```bash
devdoctor run -- rails server
devdoctor run -- python manage.py runserver
devdoctor run -- node server.js
devdoctor run -- bundle exec sidekiq
devdoctor run -- java -jar app.jar
```

**What you see in the terminal:**

```
[devdoctor] Workspace : ~/.devdoctor/projects/myapp-a1b2c3d4

=> Booting Puma
=> Rails 7.1.3 application starting in development
* Listening on http://127.0.0.1:3000

Started GET "/" for 127.0.0.1 at 2024-03-01 14:02:11
  User Load (1.8ms)  SELECT "users".* FROM "users" WHERE "users"."id" = $1
Completed 200 OK in 142ms (Views: 88.4ms | ActiveRecord: 14.2ms)

ERROR: PG::ConnectionBad: could not connect to server
^C
[devdoctor] Snapshot saved → ~/.devdoctor/projects/myapp-a1b2c3d4/sessions/session-20240301T140300Z.json
```

---

## Watch mode

Tails an existing log file continuously. Handles log rotation automatically — if the file is renamed and a new one is created (logrotate, etc.), devdoctor reopens it without missing a line.

```bash
devdoctor watch <file>
devdoctor watch --log <file>
```

**Examples:**

```bash
devdoctor watch log/development.log
devdoctor watch --log /var/log/nginx/access.log
devdoctor watch log/production.log
```

**What you see:**

```
[devdoctor] Workspace : ~/.devdoctor/projects/myapp-a1b2c3d4
[devdoctor] Watching: /Users/you/myapp/log/development.log
[devdoctor] Press Ctrl+C to stop

  User Load (2.1ms)  SELECT "users".* FROM "users" WHERE "id" = 42
ERROR: undefined method 'email' for nil:NilClass
Completed 500 Internal Server Error in 18ms

[devdoctor] Warning: development.log has not been updated for 8s
```

---

## HTML output

Add `--html` to either `run` or `watch`. devdoctor creates an HTML file that auto-refreshes every 2 seconds while your session is live, opens it in your default browser automatically, and freezes it as a shareable static report when you stop. Pass `--no-open` if you want the file written without opening a browser window.

```bash
devdoctor run   --html                        -- rails server
devdoctor watch --html                        log/development.log
devdoctor watch --html --html-dir ~/Desktop   log/production.log
devdoctor run   --html --no-open              -- bundle exec sidekiq
```

**What the HTML shows:**

The report has eight core tabs, plus an extra **Autofix** tab in `--autofix apply` mode:

| Tab | Includes |
|-----|----------|
| **All** | Every event, newest at the bottom |
| **Requests** | Rails-style request traces grouped by request id / endpoint, with a per-request timeline waterfall for DB, cache, external API, render, and controller/app time |
| **Hotspots** | Ranked route / endpoint hotspots aggregated from all saved DevDoctor sessions for this project plus the live session |
| **Errors** | `error` (ERROR/FATAL lines) |
| **Latency** | `latency` (Completed N in Xms) |
| **Queries** | `db_query` (ActiveRecord timed queries) and `query` (bare SELECT) |
| **Warnings** | Canonical warning issues grouped by fingerprint with count badges and latest examples |
| **Suggestions** | Actionable issue cards with status (`suggested`, `applied`, `failed`, `cleared`) plus fix guidance and autofix metadata |
| **Autofix** | Built-in patch candidates grouped into ready, applied, and needs-attention sections (`apply` mode only) |

Duration cells are colour-coded: red (>500 ms), yellow (>200 ms), green (≤200 ms). Click any row's **Raw** cell to expand the full original log line.

Duplicate warnings are collapsed by default, so repeated Bullet or deprecation lines stay on one card while the count keeps climbing. On the next run, fingerprints that disappear are marked as **cleared** in the Suggestions tab and in the saved snapshot JSON.

The header updates live with per-tab counts plus LIVE / DONE status.

## Autofix

devdoctor now supports three autofix modes:

```bash
devdoctor run --html --autofix -- rails server
devdoctor run --html --autofix off|suggest|apply -- rails server
```

- bare `--autofix`: same as `--autofix suggest`
- `off`: detect issues only
- `suggest`: attach fix guidance plus structured patch candidates in the Suggestions tab and snapshot JSON
- `apply`: auto-apply only built-in high-confidence, low-risk rules during the live session as soon as devdoctor finds a safe target

Current safe auto-apply scope:

- Bullet `AVOID eager loading detected` fixes when Bullet exposes an exact `.includes(...)`, `.preload(...)`, or `.eager_load(...)` snippet and devdoctor can map that snippet to one unambiguous file using callstack, request controller/action, model hints, or a project search
- Local port-collision fixes when logs show `EADDRINUSE` / `address already in use` and devdoctor can find one unambiguous config or source location to bump to the next local port

When a rule is eligible, devdoctor logs `Autofix applying -> ...` immediately, writes the change while the session is still running, and then logs the applied or failed result. The Suggestions and Autofix views show the target file, rule id, and a patch preview. In `apply` mode, the Autofix tab is visible so you can inspect ready/applied/blocked patches directly. Outside apply mode, that tab stays hidden and the same metadata appears only on Suggestions cards. For Ruby, Python, JavaScript, and Go files, devdoctor also runs a lightweight syntax check or formatter-based verification after patching and records that result on the card.

Important: `devdoctor run --autofix apply -- bundle exec rails s ...` now patches eligible files during the session, not only after you stop Rails. If a fix stays unavailable, devdoctor keeps retrying when the issue count or request context changes, and the remaining blocked items are still summarized when the session closes.

**Output path:**

```
Default : ~/.devdoctor/projects/<name-hash>/output/output-<timestamp>.html
Custom  : devdoctor watch --html --html-dir /path/to/dir log/dev.log
Quiet   : devdoctor watch --html --no-open log/dev.log
```

---

## Configuration

Drop a `devdoctor.toml` in the directory where you run devdoctor to override any detection pattern:

```toml
# devdoctor.toml
[patterns]
latency = 'Request took (?P<duration>\d+)ms'
error   = 'CRITICAL: (?P<message>.*)'
```

Patterns you define replace the matching built-in. Patterns you don't mention stay as defaults.

Noise controls let you tune the grouped warning/suggestion views:

```toml
[noise]
min_count_to_show = 1
ignore_patterns = ["healthcheck", "favicon.ico"]
silence_after_clear = true
```

`min_count_to_show` only affects grouped warning cards. `ignore_patterns` hides matching issue fingerprints from Warnings and Suggestions. `silence_after_clear` prevents already-cleared issues from being repeatedly carried forward on later runs.

**Built-in patterns:**

| Name | What it matches | Extracted fields |
|------|----------------|-----------------|
| `latency` | `Completed 200 OK in 142ms` (Rails) | `duration` |
| `latency_http` | `GET /api 200 142.123 ms` (Express/Morgan) | `duration` |
| `latency_gin` | `[GIN] … \| 200 \| 3.1ms \|` (Go/Gin) | `duration` |
| `error` | `ERROR: …` / `FATAL: …` / `CRITICAL: …` | `message` |
| `panic` | `panic: …` / `fatal error: …` (Go) · `Uncaught TypeError: …` (Node) | `message` |
| `oom` | `JavaScript heap out of memory` (Node) · `OutOfMemoryError` (Java) · `runtime: out of memory` (Go) | — |
| `connection` | `ECONNREFUSED` / `ECONNRESET` / `EADDRINUSE` · `connection refused` · `connection reset by peer` | — |
| `timeout` | `context deadline exceeded` / `context canceled` (Go) · `ETIMEDOUT` · `timed out` · `i/o timeout` | — |
| `concurrency` | `DATA RACE` (Go -race) · `goroutines are asleep - deadlock` · `deadlock detected` (Postgres/MySQL) | — |
| `unhandled` | `UnhandledPromiseRejectionWarning: …` / `UnhandledPromiseRejection: …` (Node) | `message` |
| `stackoverflow` | `Maximum call stack size exceeded` (Node) · `StackOverflowError` (Java) · `goroutine stack exceeds` (Go) | — |
| `traceback` | `Traceback (most recent call last):` (Python) | — |
| `db_query` | `Account Load (531.5ms) SELECT …` (ActiveRecord) | `table`, `duration` |
| `query` | `SELECT … FROM tablename` (bare SQL) | `table` |
| `eager_load` | `AVOID eager loading detected` / `Model => [assoc]` (Bullet) | `table`, `message` |
| `deprecation` | `DEPRECATION WARNING: …` (Rails) | `message` |
| `warning` | `!!! gem warning text` | `message` |

**Every pattern must use named capture groups** (`(?P<name>...)`) so devdoctor knows which field to populate in the event.

---

## Normalised event format

Every line produces one event:

```json
{
  "type":     "latency",
  "message":  null,
  "duration": "142",
  "table":    null,
  "raw":      "Completed 200 OK in 142ms"
}
```

JSON-structured log lines (Node, Go, Python structlog, etc.) are detected first:

```json
{"level":"error","message":"JWT expired","duration":5}
```

Snapshots also persist grouped `issues` alongside raw `events`, including counts, latest example, status, and suggestion metadata.

becomes:

```json
{
  "type":     "error",
  "message":  "JWT expired",
  "duration": "5",
  "table":    null,
  "raw":      "{\"level\":\"error\",\"message\":\"JWT expired\",\"duration\":5}"
}
```

---

## Snapshots

All events from a session are saved automatically when you press `Ctrl+C` or when the process receives `SIGTERM`:

```
~/.devdoctor/projects/<name>-<hash>/sessions/session-<timestamp>.json
```

```json
{
  "generated_at": "2024-03-01T14:03:00+00:00",
  "events": [
    {
      "type": "latency",
      "duration": "142",
      "message": null,
      "table": null,
      "raw": "Completed 200 OK in 142ms"
    },
    {
      "type": "error",
      "message": "PG::ConnectionBad: could not connect to server",
      "duration": null,
      "table": null,
      "raw": "ERROR: PG::ConnectionBad: could not connect to server"
    }
  ]
}
```

Snapshots are written atomically (`.tmp` + rename) — a crash mid-write never corrupts the file.

---

## CLI reference

```
devdoctor [--version] [--env ENV] <command> [options]

Commands
  run     Execute a command and stream its logs
  watch   Tail a log file

devdoctor run [--html] [--html-dir DIR] [--open|--no-open] [--autofix MODE] -- <command ...>
devdoctor watch [--html] [--html-dir DIR] [--open|--no-open] [--autofix MODE] [--log FILE] [FILE]

Global flags
  --version        Print version and exit
  --env ENV        Label this session with an environment name (e.g. staging)
  --help           Show help for any command

HTML flags (available on both run and watch)
  --html           Generate a live-updating HTML report and open it automatically
  --html-dir DIR   Directory for the HTML file
  --open           Explicitly open the HTML report (default with --html)
  --no-open        Generate the HTML report without opening a browser window

Autofix flags
  --autofix [MODE] off, suggest, or apply
                   passing bare --autofix defaults to suggest
                   apply runs only built-in low-risk rules
                   apply patches eligible files during the live session
```

Run `devdoctor run --help` or `devdoctor watch --help` for full option details and examples.

---

## What devdoctor does NOT do

- No dashboard server — the HTML is a static file, no port required
- No database — everything lives in `~/.devdoctor/`
- No network calls — 100% local
- No log modification — your original output is never altered
- No plugins — extend via `devdoctor.toml` patterns only (v1)

---

## File layout

```
~/.devdoctor/
  projects/
    myapp-a1b2c3d4/
      sessions/
        session-20240301T140300Z.json   ← JSON snapshots
      output/
        output-20240301T140300Z.html    ← HTML reports
```

---

## Project structure

```
devdoctor/
  cli.py            argparse entry point + help text
  runner.py         subprocess execution + thread-safe queue streaming
  watcher.py        file tail + inode rotation detection + stale warnings
  parser/
    engine.py       JSON-first parser with regex fallback
    patterns.py     built-in regex patterns
  config/
    loader.py       devdoctor.toml loader with safe merge + fallback
  snapshot/
    manager.py      SIGINT/SIGTERM handler + atomic JSON persist
  output/
    html_writer.py  live HTML report with scroll-preserving auto-refresh
  utils/
    project.py      CWD-based project name + hash helpers
```

---

## Requirements

- Python 3.9+
- `tomli` (only on Python < 3.11 — auto-installed; 3.11+ has it in stdlib)

---

## License

MIT — see [LICENSE](LICENSE).
