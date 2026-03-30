"""devdoctor CLI entry point."""

import argparse
import sys
import textwrap

from . import __version__
from .config.loader import load_config
from .issues import IssueTracker
from .parser.engine import ParserEngine
from .request_traces import RequestTraceTracker
from .snapshot.manager import SnapshotManager, load_latest_snapshot
from .utils import color
from .utils.project import get_project_id, get_sessions_dir, get_output_dir


# ── Help text ──────────────────────────────────────────────────────────────────

_ROOT_EPILOG = textwrap.dedent("""\
examples:
  devdoctor run -- rails server
  devdoctor run --html -- node server.js
  devdoctor watch log/development.log
  devdoctor watch --html log/production.log
  devdoctor watch --html --html-dir ~/Desktop log/production.log

tip:
  Place a devdoctor.toml in your project root to override detection patterns.
  Run any subcommand with --help for more options.

autofix:
  --autofix off|suggest|apply controls patch planning.
  apply only touches built-in high-confidence rules.

docs:
  https://github.com/tusharravindran/devdoctor
""")

_RUN_EPILOG = textwrap.dedent("""\
examples:
  devdoctor run -- rails server
  devdoctor run -- python manage.py runserver
  devdoctor run -- node server.js
  devdoctor run --html -- bundle exec sidekiq
  devdoctor run --html --autofix suggest -- rails server
  devdoctor run --html --autofix apply -- rails server
  devdoctor run --html --no-open -- bundle exec sidekiq
  devdoctor run --html --html-dir /tmp/logs -- java -jar app.jar

notes:
  Use -- to separate devdoctor flags from the target command.
  stdout and stderr are both captured and streamed in real time.
  --html opens the live report automatically unless you pass --no-open.
  --autofix apply runs built-in low-risk rules during the live session as soon as a safe target is found.
  Press Ctrl+C to stop — a JSON snapshot is saved automatically.
""")

_WATCH_EPILOG = textwrap.dedent("""\
examples:
  devdoctor watch log/development.log
  devdoctor watch --log /var/log/nginx/access.log
  devdoctor watch --html log/production.log
  devdoctor watch --html --autofix suggest log/development.log
  devdoctor watch --html --no-open log/production.log
  devdoctor watch --html --html-dir ~/Desktop/reports log/dev.log

notes:
  The file must exist before watching starts.
  A warning is printed if the file goes quiet for more than 5 seconds.
  Log rotation (file renamed, new file created) is detected automatically.
  --html opens the live report automatically unless you pass --no-open.
  --autofix apply can patch eligible files while the log is still streaming.
  Press Ctrl+C to stop — a JSON snapshot is saved automatically.
""")


# ── Shared flag helpers ────────────────────────────────────────────────────────

def _add_html_args(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--html",
        action="store_true",
        help=(
            "Generate a live-updating HTML report. "
            "Refreshes every 2s while running, opens in your browser automatically, "
            "and is finalised on exit."
        ),
    )
    subparser.add_argument(
        "--html-dir",
        metavar="DIR",
        dest="html_dir",
        help=(
            "Directory for the HTML file. "
            "Default: ~/.devdoctor/projects/<project>/output/"
        ),
    )
    browser_group = subparser.add_mutually_exclusive_group()
    browser_group.add_argument(
        "--open",
        action="store_true",
        dest="open_browser",
        help="Open the HTML report in your default browser immediately (default with --html).",
    )
    browser_group.add_argument(
        "--no-open",
        action="store_true",
        dest="no_open_browser",
        help="Generate the HTML report without opening a browser window.",
    )


def _add_autofix_args(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--autofix",
        nargs="?",
        choices=("off", "suggest", "apply"),
        const="suggest",
        default="off",
        help=(
            "Autofix mode: off disables patch planning, suggest attaches structured "
            "patch candidates, and apply runs only built-in high-confidence rules. "
            "Passing --autofix with no value defaults to suggest."
        ),
    )


# ── Argument parser ────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="devdoctor",
        description=(
            "devdoctor — real-time log diagnostics for backend developers.\n"
            "Parses, classifies, and snapshots every log event from any command or file."
        ),
        epilog=_ROOT_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    root.add_argument(
        "--version",
        action="version",
        version=f"devdoctor {__version__}",
        help="Show version and exit",
    )
    root.add_argument(
        "--env",
        metavar="ENV",
        help="Environment label attached to this session (e.g. staging, production)",
    )

    sub = root.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # ── run ───────────────────────────────────────────────────────────────────
    run_p = sub.add_parser(
        "run",
        help="Execute a command and stream its stdout + stderr through devdoctor",
        description=(
            "Wraps any shell command, captures both stdout and stderr, "
            "and streams every line through the parser pipeline in real time.\n\n"
            "The original output is still printed, and devdoctor adds compact "
            "colored annotations for detected issues, warnings, and latency."
        ),
        epilog=_RUN_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    run_p.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        metavar="-- <command>",
        help="Command to run, including all its arguments",
    )
    _add_html_args(run_p)
    _add_autofix_args(run_p)

    # ── watch ─────────────────────────────────────────────────────────────────
    watch_p = sub.add_parser(
        "watch",
        help="Tail a log file and stream new lines through devdoctor",
        description=(
            "Tails a log file continuously (like `tail -f`), streaming every new "
            "line through the parser pipeline.\n\n"
            "Handles log rotation automatically by tracking the file's inode. "
            "Warns you if the file goes quiet for more than 5 seconds."
        ),
        epilog=_WATCH_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    watch_p.add_argument(
        "--log",
        metavar="FILE",
        dest="log_file",
        help="Log file to watch (alternative to positional argument)",
    )
    watch_p.add_argument(
        "log_positional",
        nargs="?",
        metavar="FILE",
        help="Log file to watch",
    )
    _add_html_args(watch_p)
    _add_autofix_args(watch_p)

    return root


# ── Startup helpers ────────────────────────────────────────────────────────────

def _print_workspace() -> None:
    sessions_dir = get_sessions_dir()
    workspace = sessions_dir.parent
    print(color.info(f"Workspace : {workspace}"), flush=True)


def _make_html_writer(args, issue_tracker, request_tracker, autofix_mode: str):
    if not getattr(args, "html", False):
        return None
    from .output.html_writer import HtmlWriter
    output_dir = get_output_dir(getattr(args, "html_dir", None))
    open_browser = _should_open_browser(args)
    return HtmlWriter(
        output_dir,
        get_project_id(),
        issue_tracker=issue_tracker,
        request_tracker=request_tracker,
        autofix_mode=autofix_mode,
        open_browser=open_browser,
    )


def _should_open_browser(args) -> bool:
    return bool(getattr(args, "html", False)) and not bool(
        getattr(args, "no_open_browser", False)
    )


def _resolve_autofix_mode(args) -> str:
    mode = str(getattr(args, "autofix", "off") or "off")
    return mode


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    _print_workspace()

    config = load_config()
    autofix_mode = _resolve_autofix_mode(args)
    if autofix_mode == "apply":
        print(
            color.info(
                "Autofix apply armed: eligible patches will be applied during the session as soon as devdoctor finds a safe target."
            ),
            flush=True,
        )
    issue_tracker = IssueTracker(
        noise_config=config.get("noise"),
        previous_snapshot=load_latest_snapshot(),
        autofix_mode=autofix_mode,
    )
    request_tracker = RequestTraceTracker()
    engine = ParserEngine(patterns=config["patterns"])
    snapshot = SnapshotManager(
        issue_tracker=issue_tracker,
        request_tracker=request_tracker,
        autofix_mode=autofix_mode,
    )
    html_writer = _make_html_writer(args, issue_tracker, request_tracker, autofix_mode)
    autofix_manager = None
    if autofix_mode == "apply":
        from .autofix import AutofixManager

        autofix_manager = AutofixManager(
            autofix_mode,
            issue_tracker,
            request_tracker=request_tracker,
        )
        snapshot.register_finalizer(autofix_manager.finalize)
    if html_writer is not None:
        snapshot.register_finalizer(html_writer.close)

    if args.command == "run":
        from .runner import run_command

        cmd = args.cmd
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]

        rc = run_command(
            cmd,
            snapshot,
            engine,
            html_writer=html_writer,
            autofix_manager=autofix_manager,
        )
        snapshot.save()
        sys.exit(rc)

    elif args.command == "watch":
        from .watcher import watch_file

        log_file = args.log_file or args.log_positional
        if not log_file:
            print(
                color.error(
                    "specify a log file — "
                    "`devdoctor watch <file>` or `devdoctor watch --log <file>`"
                ),
                file=sys.stderr,
            )
            sys.exit(1)

        rc = watch_file(
            log_file,
            snapshot,
            engine,
            html_writer=html_writer,
            autofix_manager=autofix_manager,
        )
        snapshot.save()
        sys.exit(rc)


if __name__ == "__main__":
    main()
