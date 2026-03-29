"""Config loader: reads devdoctor.toml, falls back to defaults."""

import sys
from pathlib import Path
from typing import Dict, Any

from ..parser.patterns import DEFAULT_PATTERNS

CONFIG_FILE = "devdoctor.toml"


def load_config(config_path: str = CONFIG_FILE) -> Dict[str, Any]:
    """
    Load configuration from TOML file.
    Falls back to defaults if file is missing or invalid.
    """
    path = Path(config_path)
    if not path.exists():
        return {"patterns": dict(DEFAULT_PATTERNS)}

    try:
        if sys.version_info >= (3, 11):
            import tomllib
            with open(path, "rb") as f:
                data = tomllib.load(f)
        else:
            try:
                import tomli
                with open(path, "rb") as f:
                    data = tomli.load(f)
            except ImportError:
                import tomllib  # type: ignore[no-redef]
                with open(path, "rb") as f:
                    data = tomllib.load(f)

        patterns = dict(DEFAULT_PATTERNS)
        if "patterns" in data and isinstance(data["patterns"], dict):
            patterns.update(data["patterns"])

        return {"patterns": patterns}

    except Exception as e:
        print(f"[devdoctor] Warning: invalid config ({e}), using defaults.", flush=True)
        return {"patterns": dict(DEFAULT_PATTERNS)}
