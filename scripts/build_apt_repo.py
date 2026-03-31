#!/usr/bin/env python3
"""Assemble a simple third-party APT repository from one or more .deb files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packaging_tools.apt_repo import AptRepoConfig, build_apt_repo, sources_list_entry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a third-party APT repository layout.")
    parser.add_argument(
        "--repo-dir",
        required=True,
        help="Output directory for the repository structure.",
    )
    parser.add_argument(
        "--distribution",
        default="stable",
        help="APT distribution / suite name (default: stable).",
    )
    parser.add_argument(
        "--component",
        default="main",
        help="APT component name (default: main).",
    )
    parser.add_argument(
        "--repo-url",
        default=None,
        help="Optional public repo URL. If provided, the script prints a matching sources.list entry.",
    )
    parser.add_argument(
        "debs",
        nargs="+",
        help="One or more .deb artifacts to publish into the repository.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    config = AptRepoConfig(
        repo_root=Path(args.repo_dir).expanduser().resolve(),
        distribution=args.distribution,
        component=args.component,
    )
    release_path = build_apt_repo(
        config=config,
        deb_paths=[Path(value).expanduser().resolve() for value in args.debs],
    )
    print(release_path)
    if args.repo_url:
        print(sources_list_entry(args.repo_url, config))


if __name__ == "__main__":
    main()
