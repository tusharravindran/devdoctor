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
