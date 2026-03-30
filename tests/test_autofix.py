import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from devdoctor.autofix import AutofixManager
from devdoctor.issues import IssueTracker
from devdoctor.request_traces import RequestTraceTracker


@contextmanager
def chdir(path: Path):
    original = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(original)


class AutofixTests(unittest.TestCase):
    def test_suggest_mode_builds_bullet_remove_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "query.rb"
            source_path.write_text(
                "AtsJobStage.includes([:ats_job_stage_actions]).where(active: true)\n",
                encoding="utf-8",
            )

            tracker = IssueTracker(autofix_mode="suggest")
            tracker.ingest(
                {
                    "type": "eager_load",
                    "table": "AtsJobStage",
                    "message": ":ats_job_stage_actions",
                    "raw": "AVOID eager loading detected",
                    "bullet_mode": "avoid",
                    "bullet_query_hint": ".includes([:ats_job_stage_actions])",
                    "bullet_callstack": [f"{source_path}:12:in `index'"],
                }
            )

            issue = tracker.snapshot_issues()[0]

            self.assertEqual(issue["status"], "suggested")
            self.assertEqual(issue["autofix"]["status"], "available")
            self.assertEqual(Path(issue["autofix"]["file"]), source_path.resolve())
            self.assertIn(".includes([:ats_job_stage_actions])", issue["autofix"]["patch_preview"])

    def test_apply_mode_updates_file_and_marks_issue_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "query.rb"
            source_path.write_text(
                "scope = AtsJobStage.includes([:ats_job_stage_actions]).where(active: true)\n",
                encoding="utf-8",
            )

            tracker = IssueTracker(autofix_mode="apply")
            tracker.ingest(
                {
                    "type": "eager_load",
                    "table": "AtsJobStage",
                    "message": ":ats_job_stage_actions",
                    "raw": "AVOID eager loading detected",
                    "bullet_mode": "avoid",
                    "bullet_query_hint": ".includes([:ats_job_stage_actions])",
                    "bullet_callstack": [f"{source_path}:12:in `index'"],
                }
            )

            AutofixManager("apply", tracker).finalize()

            updated = source_path.read_text(encoding="utf-8")
            self.assertNotIn(".includes([:ats_job_stage_actions])", updated)

            issue = tracker.snapshot_issues()[0]
            self.assertEqual(issue["status"], "applied")
            self.assertEqual(issue["autofix"]["status"], "applied")

    def test_process_pending_applies_fix_before_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "query.rb"
            source_path.write_text(
                "scope = AtsJobStage.includes([:ats_job_stage_actions]).where(active: true)\n",
                encoding="utf-8",
            )

            tracker = IssueTracker(autofix_mode="apply")
            tracker.ingest(
                {
                    "type": "eager_load",
                    "table": "AtsJobStage",
                    "message": ":ats_job_stage_actions",
                    "raw": "AVOID eager loading detected",
                    "bullet_mode": "avoid",
                    "bullet_query_hint": ".includes([:ats_job_stage_actions])",
                    "bullet_callstack": [f"{source_path}:12:in `index'"],
                }
            )

            manager = AutofixManager("apply", tracker)
            manager.process_pending()

            updated = source_path.read_text(encoding="utf-8")
            self.assertNotIn(".includes([:ats_job_stage_actions])", updated)

            issue = tracker.snapshot_issues()[0]
            self.assertEqual(issue["status"], "applied")
            self.assertEqual(issue["autofix"]["status"], "applied")

    def test_apply_mode_can_find_controller_file_without_direct_callstack_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            controller_path = project / "app" / "controllers" / "api" / "v1" / "me_controller.rb"
            controller_path.parent.mkdir(parents=True, exist_ok=True)
            controller_path.write_text(
                "class Api::V1::MeController < ApplicationController\n"
                "  def show\n"
                "    scope = AtsJobStage.includes([:ats_job_stage_actions]).where(active: true)\n"
                "  end\n"
                "end\n",
                encoding="utf-8",
            )

            request_tracker = RequestTraceTracker()
            request_id = "123e4567-e89b-42d3-a456-426614174000"
            request_tracker.ingest(
                {
                    "type": "log",
                    "raw": f"[tushar-admin] [{request_id}] Processing by Api::V1::MeController#show as JSON",
                    "request_id": request_id,
                }
            )

            tracker = IssueTracker(autofix_mode="apply")
            tracker.ingest(
                {
                    "type": "eager_load",
                    "table": "AtsJobStage",
                    "message": ":ats_job_stage_actions",
                    "raw": "AVOID eager loading detected",
                    "request_id": request_id,
                    "bullet_mode": "avoid",
                    "bullet_query_hint": ".includes([:ats_job_stage_actions])",
                    "bullet_callstack": ["app/views/api/v1/me/show.json.jbuilder:12"],
                }
            )

            with chdir(project):
                AutofixManager("apply", tracker, request_tracker=request_tracker).finalize()

            updated = controller_path.read_text(encoding="utf-8")
            self.assertNotIn(".includes([:ats_job_stage_actions])", updated)
            issue = tracker.snapshot_issues()[0]
            self.assertEqual(issue["status"], "applied")
            self.assertEqual(Path(issue["autofix"]["file"]), controller_path.resolve())

    def test_port_collision_rule_updates_node_port_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir)
            env_path = project / ".env"
            env_path.write_text("PORT=3000\n", encoding="utf-8")

            with chdir(project):
                tracker = IssueTracker(autofix_mode="apply")
                tracker.ingest(
                    {
                        "type": "connection",
                        "raw": "Error: listen EADDRINUSE: address already in use :::3000",
                    }
                )

                AutofixManager("apply", tracker).finalize()

            updated = env_path.read_text(encoding="utf-8")
            self.assertNotIn("PORT=3000", updated)
            self.assertRegex(updated, r"PORT=30\d{2}")

            issue = tracker.snapshot_issues()[0]
            self.assertEqual(issue["status"], "applied")
            self.assertEqual(Path(issue["autofix"]["file"]), env_path.resolve())


if __name__ == "__main__":
    unittest.main()
