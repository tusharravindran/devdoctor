#!/usr/bin/env python3
"""Build a .deb package for devdoctor from an existing wheel."""

from __future__ import annotations

import argparse
from pathlib import Path

from packaging_tools.deb import DebBuildConfig, build_deb, find_wheel, load_project_metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Debian package for devdoctor.")
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root containing pyproject.toml and dist/ (default: current directory).",
    )
    parser.add_argument(
        "--dist-dir",
        default=None,
        help="Directory containing the built wheel (default: <project-root>/dist).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for the .deb artifact (default: <project-root>/dist).",
    )
    parser.add_argument(
        "--wheel",
        default=None,
        help="Explicit wheel path to package (default: auto-detect the current project wheel).",
    )
    parser.add_argument(
        "--maintainer",
        required=True,
        help='Debian Maintainer field, for example: "DevDoctor Maintainers <maintainers@example.com>".',
    )
    parser.add_argument(
        "--revision",
        default="1",
        help="Debian package revision suffix (default: 1).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    dist_dir = Path(args.dist_dir).expanduser().resolve() if args.dist_dir else project_root / "dist"
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else dist_dir

    metadata = load_project_metadata(project_root / "pyproject.toml")
    wheel_path = (
        Path(args.wheel).expanduser().resolve()
        if args.wheel
        else find_wheel(dist_dir, metadata["name"], metadata["version"])
    )

    deb_path = build_deb(
        config=DebBuildConfig(
            project_root=project_root,
            maintainer=args.maintainer,
            revision=args.revision,
            package_name=metadata["name"],
        ),
        wheel_path=wheel_path,
        output_dir=output_dir,
    )
    print(deb_path)


if __name__ == "__main__":
    main()
