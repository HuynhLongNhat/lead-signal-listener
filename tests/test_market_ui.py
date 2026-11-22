"""Offline smoke tests for UI research orchestration. No network needed."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from market_intelligence.service import ResearchController


class ResearchControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager = ResearchController(self.tmp.name)

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.manager.validate({"industry": "", "region": "Quy Nhơn"})
        with self.assertRaises(ValueError):
            self.manager.validate({"industry": "F&B", "region": "QN", "web": False, "listener": False})
        with self.assertRaises(ValueError):
            self.manager.validate({"industry": "F&B", "region": "QN", "web": "false"})

    def test_queries(self):
        cfg = self.manager.validate({"industry": "F&B", "region": "Quy Nhơn", "pain": "ít khách"})
        self.assertTrue(any("ít khách" in q for q in self.manager.queries(cfg)))

    def test_listener_only_without_db_fails_gracefully(self):
        self.manager.start({"industry": "F&B", "region": "Quy Nhơn", "web": False, "listener": True})
        for _ in range(200):
            status = self.manager.status()
            if not status["running"]:
                break
            time.sleep(.01)
        self.assertFalse(status["running"])
        self.assertEqual(status["stage"], "failed")
        self.assertTrue(status["errors"])
        self.assertEqual(self.manager.report()["opportunities"], [])

    def test_web_pipeline_wired_and_report(self):
        def fake_run(store, **kwargs):
            from market_intelligence.core import Evidence
            item = Evidence(url="https://example.org/1", source="searxng",
                title="Quán khó tìm khách", excerpt="Quán không có khách", query="F&B")
            store.put(item)
            store.analyze(item)
            return {"found": 1, "new_evidence": 1, "pain_matches": 1, "errors": [], "report": store.report()}
        with patch("market_intelligence.service.run_web", side_effect=fake_run):
            self.manager.start({"industry": "F&B", "region": "Quy Nhơn", "listener": False})
            for _ in range(200):
                status = self.manager.status()
                if not status["running"]:
                    break
                time.sleep(.01)
        self.assertEqual(status["stage"], "done")
        self.assertEqual(status["found"], 1)
        self.assertTrue(self.manager.report()["opportunities"])


if __name__ == "__main__":
    unittest.main()
