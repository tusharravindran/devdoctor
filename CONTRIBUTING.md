# Developer Documentation & Contributing Guide

This document covers everything you need to contribute to devdoctor, cut a release, and publish to Homebrew or the third-party Ubuntu/Debian package feed.

---

## Table of contents

**Contributing**
1. [How to contribute](#1-how-to-contribute)
2. [Setting up a dev environment](#2-setting-up-a-dev-environment)
3. [Branch & commit conventions](#3-branch--commit-conventions)
4. [Submitting a pull request](#4-submitting-a-pull-request)

**Releasing**

5. [Release process (step by step)](#5-release-process-step-by-step)
6. [Versioning policy](#6-versioning-policy)

**Homebrew**

7. [How the Homebrew tap works](#7-how-the-homebrew-tap-works)
8. [Setting up the personal tap (first time)](#8-setting-up-the-personal-tap-first-time)
9. [Publishing a new release to Homebrew](#9-publishing-a-new-release-to-homebrew)
10. [Testing the formula locally](#10-testing-the-formula-locally)
11. [Submitting to homebrew-core (future)](#11-submitting-to-homebrew-core-future)

**Architecture**

12. [Architecture overview](#12-architecture-overview)
13. [Data flow](#13-data-flow)
14. [Module reference](#14-module-reference)
15. [How the parser works](#15-how-the-parser-works)
16. [How the HTML writer works](#16-how-the-html-writer-works)
17. [How snapshots work](#17-how-snapshots-work)
18. [Thread safety model](#18-thread-safety-model)
19. [Adding a new event type](#19-adding-a-new-event-type)
20. [Adding a new pattern](#20-adding-a-new-pattern)
21. [Code review notes (v1)](#21-code-review-notes-v1)

---

## 1. How to contribute

### Reporting a bug

1. Search [existing issues](https://github.com/tusharravindran/devdoctor/issues) first
2. Open a new issue with:
   - devdoctor version (`devdoctor --version`)
   - Python version (`python3 --version`)
   - OS and shell
   - The exact command you ran
   - What you expected vs what happened
   - The full terminal output

### Requesting a feature

Open an issue tagged `enhancement`. Describe the problem you want solved, not just the solution. Check [PHASE2.md](PHASE2.md) first — your idea may already be on the roadmap.

### Contributing code

- Bug fixes and documentation changes: open a PR directly
- New features: open an issue first to discuss approach before writing code
- All PRs must target the `main` branch

---

## 2. Setting up a dev environment

```bash
git clone git@github.com-tusharravindran:tusharravindran/devdoctor.git
cd devdoctor

python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

If dev dependencies aren't installed yet (no `[dev]` extras defined), install manually:

```bash
pip install -e .
pip install pytest pytest-cov
```

**Verify the install:**

```bash
devdoctor --version
# devdoctor 1.0.0

devdoctor --help
```

**Run the manual smoke test:**

```bash
devdoctor run -- python3 -c "
print('Completed 200 OK in 142ms')
print('ERROR: something broke')
print('SELECT id FROM users WHERE active=1')
"
```

Expected: all three lines printed, snapshot saved, events classified as `latency`, `error`, `query`.

**Test watch mode:**

```bash
echo "" > /tmp/devdoctor-test.log
devdoctor watch /tmp/devdoctor-test.log &
sleep 0.5
echo "Completed 200 OK in 99ms"   >> /tmp/devdoctor-test.log
echo "ERROR: disk full"           >> /tmp/devdoctor-test.log
sleep 0.5
kill %1
```

Expected: both lines appear in terminal, snapshot saved.

**Test HTML output:**

```bash
devdoctor run --html --html-dir /tmp/dd-test -- python3 -c "print('ERROR: test')"
open /tmp/dd-test/output-*.html    # macOS
```

---

## 3. Branch & commit conventions

### Branch names

```
feat/short-description      new feature
fix/short-description       bug fix
chore/short-description     maintenance, deps, config
docs/short-description      documentation only
```

### Commit message format

```
<type>: <short summary in present tense>

<optional body — explain why, not what>

Co-Authored-By: Your Name <you@example.com>
```

Types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`

**Examples:**

```
feat: add --filter flag to watch and run commands
fix: reopen file handle on log rotation in watch mode
chore: bump version to 1.1.0
docs: add Homebrew tap setup instructions
```

---

## 4. Submitting a pull request

1. Fork the repo and create a branch from `main`
2. Make your changes
3. Run the smoke tests above manually (automated tests coming in v2)
4. Push your branch and open a PR against `main`
5. Fill in the PR template:
   - What does this PR do?
   - How was it tested?
   - Does it change any CLI flags or output format?
6. A maintainer will review and merge

---

## 5. Release process (step by step)

This is the complete sequence for cutting a new release and publishing to PyPI, Homebrew, and optional Ubuntu/Debian artifacts.

### Step 1 — Bump version

Edit two files:

```bash
# devdoctor/__init__.py
__version__ = "1.1.0"

# pyproject.toml
version = "1.1.0"
```

### Step 2 — Commit the version bump

```bash
git add devdoctor/__init__.py pyproject.toml
git commit -m "chore: bump version to 1.1.0"
```

### Step 3 — Create and push the tag

```bash
git tag     
git push origin main
git push origin v1.1.0
```

### Step 4 — Create the GitHub release

```bash
gh release create v1.1.0 \
  --title "devdoctor v1.1.0" \
  --notes "$(cat <<'EOF'
## What's new in v1.1.0

- Short bullet list of changes

### Install / upgrade
\`\`\`bash
pip install --upgrade devdoctor
\`\`\`
EOF
)"
```

This creates the release page and the downloadable source tarball at:
`https://github.com/tusharravindran/devdoctor/archive/refs/tags/v1.1.0.tar.gz`

### Step 5 — Build the distribution

```bash
pip install build
python -m build
ls dist/
# devdoctor-1.1.0.tar.gz
# devdoctor-1.1.0-py3-none-any.whl
```

### Step 6 — Publish to PyPI (optional but recommended)

```bash
pip install twine
twine upload dist/*
```

You will be prompted for your PyPI credentials. After this, users can install with:

```bash
pip install devdoctor          # fresh install
pip install --upgrade devdoctor  # upgrade
```

### Step 7 — Get the SHA256 of the GitHub tarball

Homebrew always downloads from the GitHub release URL, not from PyPI. Get the SHA256 of that specific tarball:

```bash
curl -sL https://github.com/tusharravindran/devdoctor/archive/refs/tags/v1.1.0.tar.gz \
  | shasum -a 256
# abc123...  -
```

Copy that hash — you need it in the next step.

### Step 8 — Update the Homebrew formula

Edit `Formula/devdoctor.rb` — change `url` and `sha256`:

```ruby
url "https://github.com/tusharravindran/devdoctor/archive/refs/tags/v1.1.0.tar.gz"
sha256 "abc123..."   # ← paste the hash from step 7
```

Also update the `test` block version string if it checks the version output:

```ruby
assert_match "devdoctor 1.1.0", shell_output("#{bin}/devdoctor --version")
```

### Step 9 — Commit and push the formula update

```bash
git add Formula/devdoctor.rb
git commit -m "chore: update Homebrew formula to v1.1.0"
git push origin main
```

### Step 10 — Sync to the Homebrew tap repo

Copy the updated formula into the `homebrew-devdoctor` tap repository (see section 8):

```bash
cp Formula/devdoctor.rb ../homebrew-devdoctor/Formula/devdoctor.rb

cd ../homebrew-devdoctor
git add Formula/devdoctor.rb
git commit -m "devdoctor 1.1.0"
git push origin main
```

Users running `brew upgrade devdoctor` will now get v1.1.0 automatically.

### Step 11 — Build a third-party Ubuntu / Debian package (optional)

Build the Python artifacts first if you have not already:

```bash
python3 -m build --no-isolation
```

Then build the `.deb`:

```bash
python3 scripts/build_deb.py \
  --project-root . \
  --maintainer "DevDoctor Maintainers <noreply@github.com>"
```

This writes a package like:

```bash
dist/devdoctor_1.2.5-1_all.deb
```

To assemble the same unsigned APT repository layout that the release workflow publishes to the `apt` branch:

```bash
python3 scripts/build_apt_repo.py \
  --repo-dir apt-repo \
  --repo-url https://raw.githubusercontent.com/tusharravindran/devdoctor/apt \
  dist/devdoctor_1.2.5-1_all.deb
```

That produces:

```bash
apt-repo/
  pool/
  dists/stable/main/binary-all/Packages
  dists/stable/main/binary-all/Packages.gz
  dists/stable/Release
```

Once that directory is hosted behind HTTPS, users can add it as a third-party source and install with:

```bash
echo "deb [trusted=yes] https://raw.githubusercontent.com/tusharravindran/devdoctor/apt stable main" | sudo tee /etc/apt/sources.list.d/devdoctor.list
sudo apt update
sudo apt install devdoctor
```

Notes:

- The generated APT repository is unsigned by default. For production use, sign `Release` / `InRelease` with your GPG key.
- The repo also includes `.github/workflows/ubuntu-package.yml` to build the `.deb`, publish the repo layout to the `apt` branch, and upload the raw artifacts on tag pushes or manual runs.

---

## 6. Versioning policy

devdoctor follows [Semantic Versioning](https://semver.org/):

```
MAJOR.MINOR.PATCH

1.0.0  →  1.0.1   Bug fix, no new features, no breaking changes
1.0.0  →  1.1.0   New feature, backwards compatible
1.0.0  →  2.0.0   Breaking change (removed flag, changed output format, etc.)
```

**What counts as breaking:**
- Removing or renaming a CLI flag
- Changing the snapshot JSON schema
- Changing the normalised event field names
- Changing the default storage path (`~/.devdoctor/`)

**What does not count as breaking:**
- Adding new CLI flags
- Adding new fields to the event dict
- Adding new event types
- Changing HTML output appearance

---

## 7. How the Homebrew tap works

Homebrew has two distribution paths:

| Path | How | Install command |
|------|-----|----------------|
| **Personal tap** | Your own `homebrew-devdoctor` GitHub repo | `brew tap tusharravindran/devdoctor && brew install devdoctor` |
| **homebrew-core** | PR to the official Homebrew repo | `brew install devdoctor` (no tap needed) |

For now devdoctor uses the **personal tap**. The formula lives in two places:

- `Formula/devdoctor.rb` in this repo (source of truth for edits)
- `Formula/devdoctor.rb` in `tusharravindran/homebrew-devdoctor` (what Homebrew reads)

When you update the formula in this repo, you must also copy it to the tap repo (step 10 of the release process above).

### How Homebrew installs devdoctor

```
brew install tusharravindran/devdoctor/devdoctor
          │              │             │
          │              │             └── formula name
          │              └── tap repo: github.com/tusharravindran/homebrew-devdoctor
          └── brew tap command prefix
```

1. Homebrew reads `Formula/devdoctor.rb` from the tap repo
2. Downloads the tarball from the `url` field
3. Verifies the `sha256`
4. Creates a virtualenv using `python@3.11`
5. Installs devdoctor and its resources (tomli) into the virtualenv
6. Symlinks `devdoctor` binary into `/opt/homebrew/bin/`

---

## 8. Setting up the personal tap (first time)

This only needs to be done once.

### Create the tap repository

The repository **must** be named `homebrew-devdoctor` (Homebrew convention):

```bash
gh repo create homebrew-devdoctor \
  --public \
  --description "Homebrew tap for devdoctor" \
  --clone
cd homebrew-devdoctor
```

### Add the formula

```bash
mkdir -p Formula
cp /path/to/devdoctor/Formula/devdoctor.rb Formula/devdoctor.rb
```

### Commit and push

```bash
git add Formula/devdoctor.rb
git commit -m "feat: add devdoctor formula v1.0.0"
git push origin main
```

### Verify it works

```bash
brew tap tusharravindran/devdoctor
brew install devdoctor
devdoctor --version
# devdoctor 1.0.0
```

### Share the install command

Anyone can now install devdoctor with:

```bash
brew tap tusharravindran/devdoctor
brew install devdoctor
```

Or in a single line:

```bash
brew install tusharravindran/devdoctor/devdoctor
```

---

## 9. Publishing a new release to Homebrew

Every time you cut a new GitHub release (after completing section 5), do this:

```bash
# 1. Get the SHA256 of the new release tarball
NEW_VERSION="1.1.0"
SHA=$(curl -sL "https://github.com/tusharravindran/devdoctor/archive/refs/tags/v${NEW_VERSION}.tar.gz" \
     | shasum -a 256 | awk '{print $1}')
echo "SHA256: $SHA"

# 2. Update the formula in this repo
sed -i '' \
  -e "s|refs/tags/v.*\.tar\.gz|refs/tags/v${NEW_VERSION}.tar.gz|" \
  -e "s|sha256 \".*\"|sha256 \"${SHA}\"|" \
  -e "s|devdoctor [0-9]*\.[0-9]*\.[0-9]*\"|devdoctor ${NEW_VERSION}\"|" \
  Formula/devdoctor.rb

# 3. Verify the change looks right
cat Formula/devdoctor.rb

# 4. Commit in this repo
git add Formula/devdoctor.rb
git commit -m "chore: update Homebrew formula to v${NEW_VERSION}"
git push origin main

# 5. Sync to the tap repo
cp Formula/devdoctor.rb ../homebrew-devdoctor/Formula/devdoctor.rb
cd ../homebrew-devdoctor
git add Formula/devdoctor.rb
git commit -m "devdoctor ${NEW_VERSION}"
git push origin main
cd -
```

After pushing, users get the new version when they run:

```bash
brew upgrade devdoctor
```

---

## 10. Testing the formula locally

Always test the formula before publishing.

### Full install test

```bash
# Uninstall current version first (if installed)
brew uninstall devdoctor

# Install from local formula file
brew install --build-from-source Formula/devdoctor.rb

# Run Homebrew's built-in test block
brew test devdoctor

# Smoke test
devdoctor --version
devdoctor run -- echo "Completed 200 OK in 55ms"
```

### Audit the formula

```bash
brew audit --strict Formula/devdoctor.rb
```

Common issues flagged by `brew audit`:
- Missing `homepage`
- SHA256 mismatch (re-run the `curl | shasum` command)
- Version string doesn't match tag

### Test the tap itself

```bash
brew tap tusharravindran/devdoctor
brew tap-info tusharravindran/devdoctor    # should show formula count = 1
brew install tusharravindran/devdoctor/devdoctor
brew test tusharravindran/devdoctor/devdoctor
```

---

## 11. Submitting to homebrew-core (future)

Once devdoctor has:
- A stable release with multiple versions
- An open-source track record (starred, watched)
- Meets [homebrew-core criteria](https://docs.brew.sh/Acceptable-Formulae)

You can submit to the official Homebrew repo so users install with just `brew install devdoctor`.

### Steps (when ready)

```bash
# 1. Fork and clone homebrew-core
gh repo fork homebrew/homebrew-core --clone
cd homebrew-core

# 2. Create a branch
git checkout -b add-devdoctor

# 3. Copy the formula
cp /path/to/devdoctor/Formula/devdoctor.rb Formula/d/devdoctor.rb

# 4. Audit strictly
brew audit --new Formula/d/devdoctor.rb

# 5. Install and test
brew install --build-from-source Formula/d/devdoctor.rb
brew test devdoctor

# 6. Open a PR to homebrew/homebrew-core
git add Formula/d/devdoctor.rb
git commit -m "devdoctor 1.0.0 (new formula)"
git push origin add-devdoctor
gh pr create --repo homebrew/homebrew-core \
  --title "devdoctor 1.0.0 (new formula)" \
  --body "Real-time log diagnostics CLI for backend developers. https://github.com/tusharravindran/devdoctor"
```

Homebrew maintainers will review the formula, run CI, and merge. After merge the personal tap can be deprecated.

---

## 12. Architecture overview

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

## 13. Data flow

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

## 14. Module reference

### `devdoctor/cli.py`

Entry point. Owns:
- `argparse` setup including all help text, epilogs, and examples
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

**Design note:** `_SENTINEL = None` signals pipe EOF from each reader thread. The main loop counts two sentinels before exiting.

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

| Function | Returns |
|----------|---------|
| `get_project_name()` | `Path.cwd().name` |
| `get_project_hash()` | MD5 of full CWD path, first 8 hex chars |
| `get_project_id()` | `"<name>-<hash>"` |
| `get_sessions_dir()` | `~/.devdoctor/projects/<id>/sessions/` (created if absent) |
| `get_output_dir(override)` | `~/.devdoctor/projects/<id>/output/` or custom path |

---

## 15. How the parser works

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

## 16. How the HTML writer works

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

## 17. How snapshots work

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

## 18. Thread safety model

| Thread | What it does | Shared state it touches |
|--------|-------------|------------------------|
| stdout reader | Reads proc.stdout, writes to sys.stdout, puts to Queue | sys.stdout (GIL-safe), Queue (thread-safe) |
| stderr reader | Reads proc.stderr, writes to sys.stdout, puts to Queue | sys.stdout (GIL-safe), Queue (thread-safe) |
| main | Drains Queue, calls parse/snapshot/html_writer | `_events` list — **sole writer** |

`sys.stdout.write` is safe from multiple threads in CPython because the GIL serialises the underlying C write call. The `Queue` is Python's thread-safe FIFO. `_events` is never touched by the reader threads.

In watch mode there is only one thread — no concurrency at all.

---

## 19. Adding a new event type

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

## 20. Adding a new pattern

Users can override patterns in `devdoctor.toml` without touching the code:

```toml
[patterns]
latency = 'Request took (?P<duration>\d+)ms'
```

To add a completely new named type from config:

```toml
[patterns]
deploy = 'Deploying (?P<message>[^\s]+) to production'
```

The event `type` will be `"deploy"`, rendering with the `log` fallback style in HTML.

---

## 21. Code review notes (v1)

| # | File | Issue | Status |
|---|------|-------|--------|
| 1 | `runner.py` | Two threads mutating `_events` directly | Fixed — queue + main-thread-only mutation |
| 2 | `snapshot/manager.py` | Direct `write_text` — partial file on crash | Fixed — `.tmp` + `os.replace` |
| 3 | `watcher.py` | File handle became stale on log rotation | Fixed — inode tracking + reopen |
| 4 | `parser/engine.py` | Patterns compiled on every `parse()` call | Fixed — compiled in `__init__` |
| 5 | `utils/project.py` | `str \| None` union syntax (requires Python 3.10) | Fixed — changed to `Optional[str]` |
| 6 | `snapshot/manager.py` | Previous SIGINT handler not chained | Known — acceptable for CLI; v2 will chain |
| 7 | `html_writer.py` | `_render()` is ~200 lines, hard to read | Known — works correctly; refactor in v2 |
| 8 | `config/loader.py` | Nested try/except for tomllib/tomli | Known — works correctly; simplifiable in v2 |
| 9 | All | No unit tests | Tracked — v2 priority |
