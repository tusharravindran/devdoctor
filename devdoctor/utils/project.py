"""Project identification utilities."""

import hashlib
from pathlib import Path
from typing import Optional


def get_project_name() -> str:
    return Path.cwd().name


def get_project_hash() -> str:
    cwd = str(Path.cwd())
    return hashlib.md5(cwd.encode()).hexdigest()[:8]


def get_project_id() -> str:
    return f"{get_project_name()}-{get_project_hash()}"


def get_sessions_dir() -> Path:
    project_id = get_project_id()
    sessions_dir = Path.home() / ".devdoctor" / "projects" / project_id / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def get_output_dir(override: Optional[str] = None) -> Path:
    """Return the HTML output directory, creating it if needed."""
    if override:
        path = Path(override).expanduser().resolve()
    else:
        project_id = get_project_id()
        path = Path.home() / ".devdoctor" / "projects" / project_id / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path
