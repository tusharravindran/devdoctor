import unittest

from devdoctor.request_traces import RequestTraceTracker


class RequestTraceTimelineTests(unittest.TestCase):
    def test_request_trace_builds_timeline_breakdown(self) -> None:
        tracker = RequestTraceTracker()
        request_id = "123e4567-e89b-42d3-a456-426614174000"

        tracker.ingest(
            {
                "type": "log",
                "raw": f'[tushar-admin] [{request_id}] Started GET "/users/42" for 127.0.0.1 at 2026-03-30 12:50:32 +0530',
                "request_id": request_id,
            }
        )
        tracker.ingest(
            {
                "type": "log",
                "raw": f"[tushar-admin] [{request_id}] Processing by UsersController#show as JSON",
                "request_id": request_id,
            }
        )
        tracker.ingest(
            {
                "type": "db_query",
                "table": "User",
                "duration": "120",
                "raw": f"[tushar-admin] [{request_id}]   User Load (120.0ms)  SELECT `users`.* FROM `users` WHERE `users`.`id` = 42 LIMIT 1",
                "request_id": request_id,
            }
        )
        tracker.ingest(
            {
                "type": "log",
                "raw": f"[tushar-admin] [{request_id}]   Redis Cache (8.0ms) GET user:42",
                "request_id": request_id,
            }
        )
        tracker.ingest(
            {
                "type": "log",
                "raw": f"[tushar-admin] [{request_id}]   Searchkick Search (900.0ms) users_development/_search",
                "request_id": request_id,
            }
        )
        tracker.ingest(
            {
                "type": "log",
                "raw": f"[tushar-admin] [{request_id}]   Rendered users/show.json.jbuilder (Duration: 15.0ms | Allocations: 100)",
                "request_id": request_id,
            }
        )
        tracker.ingest(
            {
                "type": "latency",
                "duration": "1046",
                "raw": f"[tushar-admin] [{request_id}] Completed 200 OK in 1046ms (Views: 15.0ms | ActiveRecord: 120.0ms)",
                "request_id": request_id,
            }
        )

        trace = tracker.get_trace(request_id)

        self.assertIsNotNone(trace)
        self.assertEqual(trace["title"], "GET /users/42")
        self.assertEqual(trace["timeline_total_ms"], 1046.0)
        self.assertEqual(
            [segment["kind"] for segment in trace["timeline"]],
            ["controller", "db", "cache", "external", "render"],
        )
        self.assertEqual(trace["timeline"][0]["duration_ms"], 3.0)
        self.assertEqual(trace["timeline"][1]["label"], "db query: User")
        self.assertEqual(trace["timeline"][3]["label"], "external api: Searchkick Search")
        self.assertEqual(trace["timeline_highlight"]["kind"], "external")
        self.assertEqual(
            [item["kind"] for item in trace["timeline_breakdown"]],
            ["external", "db", "render", "cache", "controller"],
        )


if __name__ == "__main__":
    unittest.main()
