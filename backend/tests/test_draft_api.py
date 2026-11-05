import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from main import app
from tests.test_r1_solver import r1_book


class DraftApiTests(unittest.TestCase):
    def test_supplied_workbook_and_review_store_reach_solver_without_overrides(self):
        workbook = r1_book()
        store = {"version": 1, "decisions": []}
        with TestClient(app) as client, patch("main.draft_schedule") as solve:
            for endpoint, kwargs in (("/api/draft-r1", {}), ("/api/draft", {"include_r2": True})):
                for status in ("blocked", "infeasible", "unknown", "model_invalid", "feasible", "optimal"):
                    solve.return_value = {"status": status, "residents": [], "blockers": []}
                    response = client.post(endpoint, json={"workbook": workbook, "store": store})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["status"], status)
                    passed_workbook, passed_store = solve.call_args.args
                    self.assertEqual(passed_workbook, workbook)
                    self.assertEqual(passed_store.model_dump(), store)
                    self.assertEqual(solve.call_args.kwargs, kwargs)

    def test_invalid_inputs_and_invalid_review_data_are_actionable(self):
        with TestClient(app) as client:
            response = client.post("/api/draft-r1", json={"workbook": {}, "store": {"version": 1, "decisions": []}})
            self.assertEqual(response.status_code, 422)
            self.assertIn("Re-import", response.json()["detail"])
            response = client.post("/api/draft-r1", json={"workbook": r1_book(), "store": {"version": 2, "decisions": []}})
            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
