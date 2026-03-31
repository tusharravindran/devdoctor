"""Helpers for assembling a simple third-party APT repository."""

from __future__ import annotations

import gzip
import hashlib
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class AptRepoConfig:
    repo_root: Path
    distribution: str = "stable"
    component: str = "main"
    architecture: str = "all"
    origin: str = "devdoctor"
    label: str = "devdoctor third-party apt repo"


def repository_layout(config: AptRepoConfig) -> Tuple[Path, Path]:
    pool_dir = config.repo_root / "pool" / config.component / "d" / "devdoctor"
    binary_dir = (
        config.repo_root
        / "dists"
        / config.distribution
        / config.component
        / f"binary-{config.architecture}"
    )
    return pool_dir, binary_dir


def sources_list_entry(repo_url: str, config: AptRepoConfig) -> str:
    return f"deb [trusted=yes] {repo_url.rstrip('/')} {config.distribution} {config.component}"


def render_release(
    *,
    config: AptRepoConfig,
    package_files: Sequence[Tuple[str, int, str, str]],
) -> str:
    date_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S UTC")
    release_lines = [
        f"Origin: {config.origin}",
        f"Label: {config.label}",
        f"Suite: {config.distribution}",
        f"Codename: {config.distribution}",
        f"Date: {date_str}",
        f"Architectures: {config.architecture}",
        f"Components: {config.component}",
        "MD5Sum:",
    ]
    for relative_path, size, md5_hex, _sha256_hex in package_files:
        release_lines.append(f" {md5_hex} {size} {relative_path}")

    release_lines.append("SHA256:")
    for relative_path, size, _md5_hex, sha256_hex in package_files:
        release_lines.append(f" {sha256_hex} {size} {relative_path}")

    return "\n".join(release_lines) + "\n"


def build_apt_repo(*, config: AptRepoConfig, deb_paths: Iterable[Path]) -> Path:
    dpkg_scanpackages = shutil.which("dpkg-scanpackages")
    if not dpkg_scanpackages:
        raise RuntimeError("dpkg-scanpackages is required to build an APT repository.")

    pool_dir, binary_dir = repository_layout(config)
    pool_dir.mkdir(parents=True, exist_ok=True)
    binary_dir.mkdir(parents=True, exist_ok=True)

    for deb_path in deb_paths:
        target = pool_dir / Path(deb_path).name
        shutil.copy2(deb_path, target)

    packages_path = binary_dir / "Packages"
    with open(packages_path, "w", encoding="utf-8") as fh:
        subprocess.run(
            [dpkg_scanpackages, "--multiversion", "pool", "/dev/null"],
            cwd=config.repo_root,
            stdout=fh,
            check=True,
        )

    packages_gz_path = binary_dir / "Packages.gz"
    with open(packages_path, "rb") as src, gzip.open(packages_gz_path, "wb") as dst:
        shutil.copyfileobj(src, dst)

    release_dir = config.repo_root / "dists" / config.distribution
    release_dir.mkdir(parents=True, exist_ok=True)

    package_files = [
        _checksum_entry(config.repo_root, packages_path),
        _checksum_entry(config.repo_root, packages_gz_path),
    ]
    (release_dir / "Release").write_text(
        render_release(config=config, package_files=package_files),
        encoding="utf-8",
    )
    return release_dir / "Release"


def _checksum_entry(repo_root: Path, path: Path) -> Tuple[str, int, str, str]:
    data = path.read_bytes()
    relative_path = str(path.relative_to(repo_root))
    return (
        relative_path,
        len(data),
        hashlib.md5(data).hexdigest(),
        hashlib.sha256(data).hexdigest(),
    )
