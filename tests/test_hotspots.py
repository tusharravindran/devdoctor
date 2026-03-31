import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from devdoctor.hotspots import HotspotTracker


class HotspotTrackerTests(unittest.TestCase):
    def test_hotspots_rank_across_saved_sessions_and_live_requests(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)
            payload = {
                "requests": [
                    {
                        "request_id": "req-1",
                        "method": "GET",
                        "path": "/users/42",
                        "title": "GET /users/42",
                        "duration": "920",
                        "warning_count": 0,
                        "error_count": 0,
                        "started_at": "2026-03-30T10:00:00+00:00",
                        "timeline_breakdown": [
                            {"kind": "external", "label": "external api", "duration_ms": 900.0},
                            {"kind": "db", "label": "db", "duration_ms": 20.0},
                        ],
                    },
                    {
                        "request_id": "req-2",
                        "method": "GET",
                        "path": "/users/17",
                        "title": "GET /users/17",
                        "duration": "480",
                        "warning_count": 1,
                        "error_count": 0,
                        "started_at": "2026-03-30T10:01:00+00:00",
                        "timeline_breakdown": [
                            {"kind": "db", "label": "db", "duration_ms": 300.0},
                        ],
                    },
                ]
            }
            (sessions_dir / "session-1.json").write_text(json.dumps(payload), encoding="utf-8")

            live_tracker = SimpleNamespace(
                traces=lambda: [
                    {
                        "request_id": "req-live",
                        "method": "GET",
                        "path": "/users/99",
                        "title": "GET /users/99",
                        "duration": "120",
                        "warning_count": 0,
                        "error_count": 0,
                        "started_at": "2026-03-30T10:02:00+00:00",
                        "timeline_breakdown": [
                            {"kind": "db", "label": "db", "duration_ms": 100.0},
                        ],
                    },
                    {
                        "request_id": "req-health",
                        "method": "GET",
                        "path": "/health",
                        "title": "GET /health",
                        "duration": "20",
                        "warning_count": 0,
                        "error_count": 0,
                        "started_at": "2026-03-30T10:03:00+00:00",
                        "timeline_breakdown": [],
                    },
                ]
            )

            tracker = HotspotTracker(
                request_tracker=live_tracker,
                noise_config={"ignore_patterns": ["health"]},
                sessions_dir=sessions_dir,
            )
            hotspots = tracker.hotspots()

            self.assertEqual(hotspots[0]["endpoint"], "GET /users/:id")
            self.assertEqual(hotspots[0]["count"], 3)
            self.assertEqual(hotspots[0]["session_count"], 2)
            self.assertEqual(hotspots[0]["p95_ms"], 920.0)
            self.assertEqual(hotspots[0]["summary"], "P95 920ms")
            self.assertEqual(hotspots[0]["dominant_label"], "external api")

            self.assertEqual(hotspots[-1]["endpoint"], "GET /health")
            self.assertTrue(hotspots[-1]["ignored"])
            self.assertEqual(hotspots[-1]["summary"], "noisy ignored")

    def test_hotspots_estimate_retry_bursts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)
            payload = {
                "requests": [
                    {
                        "request_id": "req-1",
                        "method": "POST",
                        "path": "/orders",
                        "title": "POST /orders",
                        "duration": "300",
                        "warning_count": 0,
                        "error_count": 1,
                        "status": "500",
                        "started_at": "2026-03-30T10:00:00+00:00",
                        "timeline_breakdown": [],
                    },
                    {
                        "request_id": "req-2",
                        "method": "POST",
                        "path": "/orders",
                        "title": "POST /orders",
                        "duration": "350",
                        "warning_count": 0,
                        "error_count": 1,
                        "status": "500",
                        "started_at": "2026-03-30T10:00:06+00:00",
                        "timeline_breakdown": [],
                    },
                ]
            }
            (sessions_dir / "session-1.json").write_text(json.dumps(payload), encoding="utf-8")

            tracker = HotspotTracker(
                request_tracker=SimpleNamespace(traces=lambda: []),
                sessions_dir=sessions_dir,
            )
            hotspots = tracker.hotspots()

            self.assertEqual(hotspots[0]["endpoint"], "POST /orders")
            self.assertEqual(hotspots[0]["retry_count"], 1)
            self.assertEqual(hotspots[0]["summary"], "1 retry")


if __name__ == "__main__":
    unittest.main()
