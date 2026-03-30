import unittest

from devdoctor.cli import _resolve_autofix_mode, _should_open_browser, build_parser


class CliHtmlFlagTests(unittest.TestCase):
    def test_html_opens_browser_by_default(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["run", "--html", "--", "python3", "app.py"])

        self.assertTrue(_should_open_browser(args))

    def test_no_open_disables_browser_launch(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["watch", "--html", "--no-open", "log/development.log"])

        self.assertFalse(_should_open_browser(args))

    def test_autofix_apply_stays_enabled_in_watch_mode(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["watch", "--autofix", "apply", "log/development.log"])

        self.assertEqual(_resolve_autofix_mode(args), "apply")

    def test_bare_autofix_defaults_to_suggest(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["run", "--autofix", "--", "python3", "app.py"])

        self.assertEqual(_resolve_autofix_mode(args), "suggest")


if __name__ == "__main__":
    unittest.main()
