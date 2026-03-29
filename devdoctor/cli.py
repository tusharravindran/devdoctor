"""devdoctor CLI entry point."""

import argparse
import sys
import textwrap

from . import __version__
from .config.loader import load_config
from .parser.engine import ParserEngine
from .snapshot.manager import SnapshotManager
from .utils.project import get_project_id, get_sessions_dir, get_output_dir


# ── Help text constants ────────────────────────────────────────────────────────

_ROOT_EPILOG = textwrap.dedent("""\
examples:
  devdoctor run -- rails server
  devdoctor run --html -- node server.js
  devdoctor watch log/development.log
  devdoctor watch --html --html-dir ~/Desktop log/production.log

tip:
  Place a devdoctor.toml in your project root to override detection patterns.
  Run any subcommand with --help for more options.

docs:
  https://github.com/<user>/devdoctor
""")

_RUN_EPILOG = textwrap.dedent("""\
examples:
  devdoctor run -- rails server
  devdoctor run -- python manage.py runserver
  devdoctor run -- node server.js
  devdoctor run --html -- bundle exec sidekiq
  devdoctor run --html --html-dir /tmp/logs -- java -jar app.jar

notes:
  Use -- to separate devdoctor flags from the target command.
  stdout and stderr are both captured and streamed in real time.
  Press Ctrl+C to stop — a JSON snapshot is saved automatically.
""")

_WATCH_EPILOG = textwrap.dedent("""\
examples:
  devdoctor watch log/development.log
  devdoctor watch --log /var/log/nginx/access.log
  devdoctor watch --html log/production.log
  devdoctor watch --html --html-dir ~/Desktop/reports log/dev.log

notes:
  The file must exist before watching starts.
  A warning is printed if the file goes quiet for more than 5 seconds.
  Log rotation (file renamed, new file created) is detected automatically.
  Press Ctrl+C to stop — a JSON snapshot is saved automatically.
""")


# ── Shared flag helper ─────────────────────────────────────────────────────────

def _add_html_args(subparser: argparse.ArgumentParser) -> None:
    """Add shared --html / --html-dir flags to a subcommand."""
    subparser.add_argument(
        "--html",
        action="store_true",
        help=(
            "Generate a live-updating HTML report. "
            "Opens as a static file in any browser. "
            "Refreshes every 2s while running; finalised on exit."
        ),
    )
    subparser.add_argument(
        "--html-dir",
        metavar="DIR",
        dest="html_dir",
        help=(
            "Directory where the HTML file is written. "
            "Default: ~/.devdoctor/projects/<project>/output/"
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
            "The original output is printed unchanged. devdoctor runs silently "
            "alongside it, classifying and recording each event."
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

    return root


# ── Startup helpers ────────────────────────────────────────────────────────────

def _print_workspace() -> None:
    sessions_dir = get_sessions_dir()
    workspace = sessions_dir.parent  # ~/.devdoctor/projects/<name-hash>
    print(f"[devdoctor] Workspace : {workspace}", flush=True)


def _make_html_writer(args):
    """Return an HtmlWriter if --html was passed, else None."""
    if not getattr(args, "html", False):
        return None
    from .output.html_writer import HtmlWriter
    output_dir = get_output_dir(getattr(args, "html_dir", None))
    return HtmlWriter(output_dir, get_project_id())


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    _print_workspace()

    config = load_config()
    engine = ParserEngine(patterns=config["patterns"])
    snapshot = SnapshotManager()
    html_writer = _make_html_writer(args)

    if args.command == "run":
        from .runner import run_command

        # Strip the optional '--' separator that isolates devdoctor flags
        # from the target command (e.g. `devdoctor run --html -- node app.js`)
        cmd = args.cmd
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]

        rc = run_command(cmd, snapshot, engine, html_writer=html_writer)
        snapshot.save()
        sys.exit(rc)

    elif args.command == "watch":
        from .watcher import watch_file

        log_file = args.log_file or args.log_positional
        if not log_file:
            print(
                "[devdoctor] Error: specify a log file — "
                "`devdoctor watch <file>` or `devdoctor watch --log <file>`",
                file=sys.stderr,
            )
            sys.exit(1)

        rc = watch_file(log_file, snapshot, engine, html_writer=html_writer)
        snapshot.save()
        sys.exit(rc)


if __name__ == "__main__":
    main()
