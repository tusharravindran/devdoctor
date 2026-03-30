import unittest

from devdoctor.parser.engine import ParserEngine


class ParserEngineBulletGroupingTests(unittest.TestCase):
    def test_flush_groups_multiline_bullet_block(self) -> None:
        parser = ParserEngine()

        self.assertEqual(parser.parse("AVOID eager loading detected\n"), [])
        self.assertEqual(parser.parse("  AtsJobStage => [:ats_job_stage_actions]\n"), [])
        self.assertEqual(
            parser.parse("  Remove from your query: .includes([:ats_job_stage_actions])\n"),
            [],
        )

        events = parser.flush()

        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["type"], "eager_load")
        self.assertEqual(event["bullet_mode"], "avoid")
        self.assertEqual(event["table"], "AtsJobStage")
        self.assertEqual(event["message"], ":ats_job_stage_actions")
        self.assertEqual(
            event["bullet_query_hint"],
            ".includes([:ats_job_stage_actions])",
        )
        self.assertIn("AVOID eager loading detected", event["raw"])
        self.assertIn("AtsJobStage => [:ats_job_stage_actions]", event["raw"])

    def test_non_bullet_line_flushes_pending_block_without_losing_next_event(self) -> None:
        parser = ParserEngine()

        parser.parse("USE eager loading detected\n")
        parser.parse("  AtsJobStageAction => [:candidate_comm_sender, :candidate_comm_template]\n")

        events = parser.parse("Completed 200 OK in 29ms\n")

        self.assertEqual(len(events), 2)
        bullet_event, next_event = events
        self.assertEqual(bullet_event["type"], "eager_load")
        self.assertEqual(bullet_event["bullet_mode"], "use")
        self.assertEqual(bullet_event["table"], "AtsJobStageAction")
        self.assertEqual(
            bullet_event["message"],
            ":candidate_comm_sender, :candidate_comm_template",
        )
        self.assertEqual(next_event["type"], "latency")
        self.assertEqual(next_event["duration"], "29")


if __name__ == "__main__":
    unittest.main()
