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

    def test_render_hotspot_cards_shows_ranked_endpoint_summary(self) -> None:
        writer = HtmlWriter.__new__(HtmlWriter)
        writer._hotspot_tracker = SimpleNamespace(
            hotspots=lambda: [
                {
                    "endpoint": "GET /users/:id",
                    "count": 12,
                    "session_count": 4,
                    "p95_ms": 920.0,
                    "avg_ms": 410.0,
                    "max_ms": 1040.0,
                    "retry_count": 2,
                    "warning_total": 3,
                    "error_total": 1,
                    "ignored": False,
                    "summary": "P95 920ms",
                    "dominant_label": "external api",
                    "dominant_ms": 900.0,
                }
            ]
        )

        html = HtmlWriter._render_hotspot_cards(writer)

        self.assertIn("Endpoint hotspots", html)
        self.assertIn("#1 hotspot", html)
        self.assertIn("GET /users/:id", html)
        self.assertIn("P95 920ms", html)
        self.assertIn("dominant external api 900ms", html)

    def test_render_request_card_includes_timeline_waterfall(self) -> None:
        writer = HtmlWriter.__new__(HtmlWriter)

        html = HtmlWriter._render_request_card(
            writer,
            {
                "title": "GET /users/42",
                "request_id": "req-123",
                "search_text": "GET /users/42 req-123",
                "completed": True,
                "duration": "1046",
                "query_count": 1,
                "warning_count": 0,
                "error_count": 0,
                "controller": "UsersController",
                "action": "show",
                "actor": "Tushar",
                "status": "200",
                "status_text": "OK",
                "timeline_total_ms": 1046.0,
                "timeline_breakdown": [
                    {"kind": "external", "label": "external api", "duration_ms": 900.0},
                    {"kind": "db", "label": "db", "duration_ms": 120.0},
                    {"kind": "render", "label": "render", "duration_ms": 15.0},
                    {"kind": "cache", "label": "cache", "duration_ms": 8.0},
                    {"kind": "controller", "label": "controller", "duration_ms": 3.0},
                ],
                "timeline_highlight": {
                    "kind": "external",
                    "label": "external api: Searchkick Search",
                    "duration_ms": 900.0,
                    "start_offset_ms": 131.0,
                },
                "timeline": [
                    {"kind": "controller", "label": "controller", "duration_ms": 3.0, "start_offset_ms": 0.0},
                    {"kind": "db", "label": "db query: User", "duration_ms": 120.0, "start_offset_ms": 3.0},
                    {"kind": "cache", "label": "cache: Redis Cache", "duration_ms": 8.0, "start_offset_ms": 123.0},
                    {"kind": "external", "label": "external api: Searchkick Search", "duration_ms": 900.0, "start_offset_ms": 131.0},
                    {"kind": "render", "label": "render: users/show.json.jbuilder", "duration_ms": 15.0, "start_offset_ms": 1031.0},
                ],
                "events": [],
            },
        )

        self.assertIn("Request timeline", html)
        self.assertIn("request-segment-bar", html)
        self.assertIn("db query: User", html)
        self.assertIn("slowest: external api: Searchkick Search", html)


if __name__ == "__main__":
    unittest.main()
