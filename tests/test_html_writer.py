import unittest
from types import SimpleNamespace

from devdoctor.output.html_writer import HtmlWriter


class HtmlWriterRowRenderingTests(unittest.TestCase):
    def test_render_rows_handles_empty_raw_text(self) -> None:
        writer = HtmlWriter.__new__(HtmlWriter)
        writer._events = [
            {
                "type": "query",
                "message": "Intro",
                "duration": "0.6",
                "table": "Intro",
                "raw": "",
                "_ts": "08:18:23",
            }
        ]

        rows = HtmlWriter._render_rows(writer)

        self.assertIn('class="ev ev-query"', rows)
        self.assertIn('data-short=""', rows)
        self.assertIn(">08:18:23<", rows)

    def test_render_autofix_cards_groups_ready_and_applied_items(self) -> None:
        writer = HtmlWriter.__new__(HtmlWriter)
        writer._issue_tracker = SimpleNamespace(
            autofix_issues=lambda: [
                {
                    "type": "eager_load",
                    "status": "suggested",
                    "title": "Unused eager loading on AtsJobStage -> ats_job_stage_actions",
                    "count": 1,
                    "first_seen_at": "2026-03-30T08:18:23+00:00",
                    "last_seen_at": "2026-03-30T08:18:23+00:00",
                    "latest_example": {"raw": "AVOID eager loading detected"},
                    "why": "Bullet reports unused eager loading.",
                    "suggestion": "Remove the unnecessary include.",
                    "confidence": "high",
                    "risk": "low",
                    "autofix": {
                        "status": "available",
                        "rule_id": "bullet_remove_exact_hint",
                        "file": "/tmp/query.rb",
                        "patch_preview": "--- before\n+++ after",
                    },
                },
                {
                    "type": "eager_load",
                    "status": "applied",
                    "title": "Unused eager loading on AtsJobStageAction -> candidate_comm_sender",
                    "count": 1,
                    "first_seen_at": "2026-03-30T08:18:23+00:00",
                    "last_seen_at": "2026-03-30T08:18:23+00:00",
                    "latest_example": {"raw": "AVOID eager loading detected"},
                    "why": "Bullet reports unused eager loading.",
                    "suggestion": "Remove the unnecessary include.",
                    "confidence": "high",
                    "risk": "low",
                    "autofix": {
                        "status": "applied",
                        "rule_id": "bullet_remove_exact_hint",
                        "file": "/tmp/query.rb",
                        "verification_status": "passed",
                    },
                },
            ]
        )

        html = HtmlWriter._render_autofix_cards(writer)

        self.assertIn("Ready auto patches", html)
        self.assertIn("Applied patches", html)
        self.assertIn("verify: passed", html)

    def test_apply_mode_shows_autofix_tab(self) -> None:
        writer = HtmlWriter.__new__(HtmlWriter)
        writer._autofix_mode = "apply"

        tab_ids = [tab["id"] for tab in HtmlWriter._visible_tabs(writer)]

        self.assertIn("autofix", tab_ids)
        self.assertIn("suggestions", tab_ids)

    def test_suggest_mode_hides_autofix_tab(self) -> None:
        writer = HtmlWriter.__new__(HtmlWriter)
        writer._autofix_mode = "suggest"

        tab_ids = [tab["id"] for tab in HtmlWriter._visible_tabs(writer)]

        self.assertNotIn("autofix", tab_ids)


if __name__ == "__main__":
    unittest.main()
