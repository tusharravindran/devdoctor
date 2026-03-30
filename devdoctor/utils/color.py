"""ANSI terminal color helpers for devdoctor's own output messages.

All functions return plain strings when stdout is not a TTY or when
NO_COLOR / DEVDOCTOR_NO_COLOR is set, so piping and CI are safe.
"""

import os
import sys

# ── ANSI escape codes ──────────────────────────────────────────────────────────
_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_DIM    = "\033[2m"
_RED    = "\033[91m"   # bright red
_GREEN  = "\033[92m"   # bright green
_YELLOW = "\033[93m"   # bright yellow
_CYAN   = "\033[96m"   # bright cyan
_BLUE   = "\033[94m"   # bright blue

_ERROR_TYPES = {
    "error", "exception", "panic", "oom", "connection",
    "concurrency", "unhandled", "stackoverflow", "traceback",
}
_WARNING_TYPES = {"warning", "deprecation", "eager_load", "timeout"}
_LATENCY_TYPES = {"latency", "latency_http", "latency_gin"}


def _tty() -> bool:
    """Return True when ANSI color should be emitted."""
    if os.environ.get("NO_COLOR") or os.environ.get("DEVDOCTOR_NO_COLOR"):
        return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"{code}{text}{_RESET}" if _tty() else text


def _prefix() -> str:
    return _c(_BOLD + _CYAN, "[devdoctor]")


# ── Public helpers — each returns a ready-to-print string ─────────────────────

def info(msg: str) -> str:
    """Cyan bold prefix + plain message.  Used for neutral status lines."""
    return f"{_prefix()} {msg}"


def success(msg: str) -> str:
    """Cyan bold prefix + green message.  Used for snapshot saved, HTML path."""
    return f"{_prefix()} {_c(_GREEN, msg)}"


def warn(msg: str) -> str:
    """Cyan bold prefix + yellow 'Warning:' + message."""
    return f"{_prefix()} {_c(_YELLOW, 'Warning:')} {msg}"


def error(msg: str) -> str:
    """Cyan bold prefix + red 'Error:' + message.  Write to stderr."""
    return f"{_prefix()} {_c(_RED, 'Error:')} {msg}"


def dim(msg: str) -> str:
    """Cyan bold prefix + dimmed message.  Used for secondary info lines."""
    return f"{_prefix()} {_c(_DIM, msg)}"


def event_annotation(event: dict) -> str:
    """Return a colored terminal annotation for a parsed event, or empty string."""
    event_type = str(event.get("type") or "log")
    message = event.get("message")
    duration = event.get("duration")
    table = event.get("table")
    raw = event.get("raw") or ""

    if event_type in _ERROR_TYPES:
        detail = message or raw or event_type
        return f"{_prefix()} {_c(_RED, 'Issue:')} {detail}"

    if event_type in _WARNING_TYPES:
        if event_type == "eager_load":
            mode = str(event.get("bullet_mode") or "").upper()
            if table and message:
                prefix = f"{mode} " if mode else ""
                detail = f"{prefix}{table} => [{message}]"
            else:
                detail = message or raw or "eager loading detected"
        else:
            detail = message or raw or event_type
        return f"{_prefix()} {_c(_YELLOW, 'Warning:')} {detail}"

    if event_type in _LATENCY_TYPES and duration is not None:
        try:
            ms = float(duration)
        except (TypeError, ValueError):
            ms = None

        if ms is not None:
            if ms > 500:
                tone = _RED
                label = "Slow:"
            elif ms > 200:
                tone = _YELLOW
                label = "Latency:"
            else:
                tone = _GREEN
                label = "Fast:"
            return f"{_prefix()} {_c(tone, label)} {ms:g}ms"

    if event_type in {"query", "db_query"}:
        # db_query has a duration — colour-code it like latency
        if event_type == "db_query" and duration is not None:
            try:
                ms = float(duration)
                table_note = f" ({table})" if table else ""
                if ms > 500:
                    return f"{_prefix()} {_c(_RED, f'Slow query: {ms:g}ms{table_note}')}"
                if ms > 200:
                    return f"{_prefix()} {_c(_YELLOW, f'Query: {ms:g}ms{table_note}')}"
                if table:
                    return f"{_prefix()} {_c(_BLUE, 'Query:')} {table} {_c(_DIM, f'{ms:g}ms')}"
            except (TypeError, ValueError):
                pass
        if table:
            return f"{_prefix()} {_c(_BLUE, 'Query:')} {table}"

    return ""
