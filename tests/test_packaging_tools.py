import unittest
from pathlib import Path

from packaging_tools.apt_repo import AptRepoConfig, render_release, sources_list_entry
from packaging_tools.deb import DebBuildConfig, default_deb_output_name, render_control, render_launcher


class DebianPackagingTests(unittest.TestCase):
    def test_render_control_includes_debian_fields(self) -> None:
        metadata = {
            "name": "devdoctor",
            "version": "1.2.4",
            "description": "Backend log diagnostics CLI",
            "homepage": "https://github.com/tusharravindran/devdoctor",
        }
        config = DebBuildConfig(
            project_root=Path("."),
            maintainer="DevDoctor Maintainers <noreply@github.com>",
        )

        control = render_control(metadata, config)

        self.assertIn("Package: devdoctor", control)
        self.assertIn("Version: 1.2.4-1", control)
        self.assertIn("Depends: python3 (>= 3.9)", control)
        self.assertIn("Homepage: https://github.com/tusharravindran/devdoctor", control)

    def test_launcher_uses_vendor_directory(self) -> None:
        launcher = render_launcher("/usr/lib/devdoctor/vendor")

        self.assertIn("VENDOR_DIR = '/usr/lib/devdoctor/vendor'", launcher)
        self.assertIn("from devdoctor.cli import main", launcher)

    def test_default_deb_output_name_uses_revision_and_architecture(self) -> None:
        metadata = {"version": "1.2.4"}
        config = DebBuildConfig(
            project_root=Path("."),
            maintainer="DevDoctor Maintainers <noreply@github.com>",
            revision="2",
        )

        self.assertEqual(
            default_deb_output_name(metadata, config),
            "devdoctor_1.2.4-2_all.deb",
        )


class AptRepoPackagingTests(unittest.TestCase):
    def test_sources_list_entry_uses_distribution_and_component(self) -> None:
        config = AptRepoConfig(repo_root=Path("/tmp/repo"), distribution="stable", component="main")

        entry = sources_list_entry("https://packages.example.com/devdoctor", config)

        self.assertEqual(
            entry,
            "deb [trusted=yes] https://packages.example.com/devdoctor stable main",
        )

    def test_render_release_lists_checksums(self) -> None:
        config = AptRepoConfig(repo_root=Path("/tmp/repo"))
        release = render_release(
            config=config,
            package_files=[
                (
                    "dists/stable/main/binary-all/Packages",
                    123,
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                )
            ],
        )

        self.assertIn("Architectures: all", release)
        self.assertIn("Components: main", release)
        self.assertIn("MD5Sum:", release)
        self.assertIn("SHA256:", release)
        self.assertIn("dists/stable/main/binary-all/Packages", release)


if __name__ == "__main__":
    unittest.main()
