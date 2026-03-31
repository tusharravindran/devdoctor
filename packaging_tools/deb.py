"""Helpers for building a third-party Debian package for devdoctor."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python <3.11
    import tomli as tomllib  # type: ignore


@dataclass(frozen=True)
class DebBuildConfig:
    project_root: Path
    maintainer: str
    revision: str = "1"
    package_name: str = "devdoctor"
    architecture: str = "all"
    section: str = "utils"
    priority: str = "optional"
    python_dependency: str = "python3 (>= 3.9)"


def load_project_metadata(pyproject_path: Path) -> Dict[str, str]:
    with open(pyproject_path, "rb") as fh:
        payload = tomllib.load(fh)

    project = payload.get("project", {})
    urls = project.get("urls", {})
    return {
        "name": str(project.get("name") or "devdoctor"),
        "version": str(project.get("version") or "0.0.0"),
        "description": str(project.get("description") or "Backend log diagnostics CLI"),
        "homepage": str(urls.get("Homepage") or urls.get("Repository") or ""),
    }


def find_wheel(dist_dir: Path, package_name: str, version: str) -> Path:
    pattern = f"{package_name}-{version}-py3-none-any.whl"
    wheel_path = dist_dir / pattern
    if wheel_path.exists():
        return wheel_path
    raise FileNotFoundError(f"Could not find built wheel: {wheel_path}")


def render_control(metadata: Dict[str, str], config: DebBuildConfig) -> str:
    version = metadata["version"]
    description = metadata["description"]
    homepage = metadata.get("homepage", "")
    long_description = (
        "DevDoctor wraps any command or tails any log file, classifies log lines in real time, "
        "saves JSON session snapshots, and generates a live HTML diagnostics report."
    )
    lines = [
        f"Package: {config.package_name}",
        f"Version: {version}-{config.revision}",
        f"Section: {config.section}",
        f"Priority: {config.priority}",
        f"Architecture: {config.architecture}",
        f"Depends: {config.python_dependency}",
        f"Maintainer: {config.maintainer}",
    ]
    if homepage:
        lines.append(f"Homepage: {homepage}")
    lines.extend(
        [
            f"Description: {description}",
            f" {long_description}",
        ]
    )
    return "\n".join(lines) + "\n"


def render_launcher(vendor_dir: str = "/usr/lib/devdoctor/vendor") -> str:
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        import os
        import sys

        VENDOR_DIR = {vendor_dir!r}
        if os.path.isdir(VENDOR_DIR):
            sys.path.insert(0, VENDOR_DIR)

        from devdoctor.cli import main

        if __name__ == "__main__":
            main()
        """
    )


def default_deb_output_name(metadata: Dict[str, str], config: DebBuildConfig) -> str:
    return f"{config.package_name}_{metadata['version']}-{config.revision}_{config.architecture}.deb"


def build_deb(
    *,
    config: DebBuildConfig,
    wheel_path: Path,
    output_dir: Path,
    python_executable: Optional[str] = None,
) -> Path:
    dpkg_deb = shutil.which("dpkg-deb")
    if not dpkg_deb:
        raise RuntimeError("dpkg-deb is required to build a Debian package.")

    metadata = load_project_metadata(config.project_root / "pyproject.toml")
    python_bin = python_executable or sys.executable
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="devdoctor-deb-") as tmpdir:
        package_root = Path(tmpdir) / "pkgroot"
        control_dir = package_root / "DEBIAN"
        vendor_dir = package_root / "usr" / "lib" / config.package_name / "vendor"
        bin_dir = package_root / "usr" / "bin"

        control_dir.mkdir(parents=True, exist_ok=True)
        vendor_dir.mkdir(parents=True, exist_ok=True)
        bin_dir.mkdir(parents=True, exist_ok=True)

        (control_dir / "control").write_text(
            render_control(metadata, config),
            encoding="utf-8",
        )

        launcher_path = bin_dir / config.package_name
        launcher_path.write_text(render_launcher(), encoding="utf-8")
        launcher_path.chmod(0o755)

        subprocess.run(
            [
                python_bin,
                "-m",
                "pip",
                "install",
                "--no-compile",
                "--target",
                str(vendor_dir),
                str(wheel_path),
            ],
            check=True,
        )

        output_path = output_dir / default_deb_output_name(metadata, config)
        subprocess.run(
            [
                dpkg_deb,
                "--build",
                "--root-owner-group",
                str(package_root),
                str(output_path),
            ],
            check=True,
        )
        return output_path
