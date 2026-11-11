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
            for status in ("blocked", "infeasible", "unknown", "model_invalid", "feasible", "optimal"):
                solve.return_value = {"status": status, "residents": [], "blockers": []}
                response = client.post("/api/draft", json={"workbook": workbook, "store": store})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], status)
                passed_workbook, passed_store = solve.call_args.args
                self.assertEqual(passed_workbook, workbook)
                self.assertEqual(passed_store.model_dump(), store)
                self.assertEqual(solve.call_args.kwargs, {"max_seconds": 120})

    def test_selected_search_budget_reaches_solver_and_invalid_budgets_are_rejected(self):
        payload = {"workbook": r1_book(), "store": {"version": 1, "decisions": []}}
        with TestClient(app) as client, patch("main.draft_schedule", return_value={"status": "optimal"}) as solve:
            for seconds in (60, 120, 300, 600):
                token = client.post('/api/draft/start').json()['token']
                response = client.post(f'/api/draft?token={token}', json={**payload, "max_seconds": seconds})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(solve.call_args.kwargs['max_seconds'], seconds)
                self.assertIn('cancel', solve.call_args.kwargs)
            solve.reset_mock()
            for invalid in (0, -1, 121, 601, "300", None):
                self.assertEqual(client.post('/api/draft', json={**payload, "max_seconds": invalid}).status_code, 422)
            solve.assert_not_called()

    def test_historical_year_is_rejected_before_running_solver(self):
        workbook = r1_book()
        workbook["available_years"] = [{"year": 2028}, {"year": 2026}, {"year": 2027}]
        with TestClient(app) as client, patch("main.draft_schedule") as solve:
            response = client.post("/api/draft", json={"workbook": workbook, "store": {"version": 1, "decisions": []}})
            self.assertEqual(response.status_code, 422)
            self.assertIn("latest planning year", response.json()["detail"])
            solve.assert_not_called()
            workbook["target_year"] = 2028
            solve.return_value = {"status": "feasible", "residents": [], "blockers": []}
            self.assertEqual(client.post("/api/draft", json={"workbook": workbook, "store": {"version": 1, "decisions": []}}).status_code, 200)
            solve.assert_called_once()

    def test_invalid_inputs_and_invalid_review_data_are_actionable(self):
        with TestClient(app) as client:
            response = client.post("/api/draft", json={"workbook": {}, "store": {"version": 1, "decisions": []}})
            self.assertEqual(response.status_code, 422)
            self.assertIn("Re-import", response.json()["detail"])
            response = client.post("/api/draft", json={"workbook": r1_book(), "store": {"version": 2, "decisions": []}})
            self.assertEqual(response.status_code, 422)




class DraftCancellationTests(unittest.TestCase):
    def test_cancel_before_start_and_restart(self):
        with TestClient(app) as client:
            token = client.post('/api/draft/start').json()['token']
            self.assertEqual(client.delete(f'/api/draft/{token}').status_code, 200)
            book = r1_book()
            book['available_years'] = [{'year': book['target_year']}]
            response = client.post(f'/api/draft?token={token}', json={'workbook': book, 'store': {'version': 1, 'decisions': []}})
            self.assertEqual(response.status_code, 409)
            next_token = client.post('/api/draft/start').json()['token']
            with patch('main.draft_schedule', return_value={'status': 'blocked', 'residents': [], 'blockers': []}):
                response = client.post(f'/api/draft?token={next_token}', json={'workbook': book, 'store': {'version': 1, 'decisions': []}})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(next_token, __import__('main')._draft_operations)

    def test_cancel_during_solve_stops_active_solver(self):
        from threading import Event, Thread
        from scheduler import DraftCancelled, _solve_priorities
        from ortools.sat.python import cp_model
        entered, stop, cancelled = Event(), Event(), Event()
        model = cp_model.CpModel()
        x = model.new_bool_var('x')
        solves = []
        def solve(solver, model, callback):
            solves.append(1)
            entered.set()
            self.assertTrue(stop.wait(3))
            return cp_model.UNKNOWN
        calls = []
        def stop_search(solver):
            calls.append(1)
            if len(calls) == 2:  # A first stop can precede OR-Tools initialization.
                stop.set()
        errors = []
        def run():
            try:
                _solve_priorities(model, [('x', x), ('again', x)], [x], 5, cancelled)
            except DraftCancelled:
                errors.append('cancelled')
        with patch('scheduler.cp_model.CpSolver.solve', new=solve), patch('scheduler.cp_model.CpSolver.stop_search', new=stop_search):
            worker = Thread(target=run)
            worker.start()
            self.assertTrue(entered.wait(3))
            cancelled.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ['cancelled'])
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(len(solves), 1)

    def test_active_cancellation_rejects_late_result_and_cleans_up(self):
        from threading import Event, Thread
        import main
        entered, release = Event(), Event()
        book = r1_book()
        book['available_years'] = [{'year': book['target_year']}]
        replies = []
        def solve(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return {'status': 'feasible', 'residents': [], 'blockers': []}
        with TestClient(app) as client, patch('main.draft_schedule', new=solve):
            token = client.post('/api/draft/start').json()['token']
            worker = Thread(target=lambda: replies.append(client.post(f'/api/draft?token={token}', json={'workbook': book, 'store': {'version': 1, 'decisions': []}})))
            worker.start()
            self.assertTrue(entered.wait(5))
            self.assertEqual(client.delete(f'/api/draft/{token}').status_code, 200)
            release.set()
            worker.join(5)
            self.assertEqual(replies[0].status_code, 409)
            self.assertNotIn(token, main._draft_operations)

if __name__ == '__main__':
    unittest.main()
