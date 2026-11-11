"""Protect the count relaxation and its use as a bound, never an assignment."""
import itertools
import unittest
from threading import Event
from copy import deepcopy
from collections import Counter
from unittest.mock import patch

from ortools.sat.python import cp_model
from scheduler import (_posting_balance_relaxation, _posting_block_relaxation, _solve_priorities,
                       draft_schedule, DraftCancelled)
from tests.test_r1_solver import STORE
from tests.test_r5_rules import r5_book
from tests.test_requirement_ledger import resident


class PostingBoundTests(unittest.TestCase):
    def test_weighted_count_bound_matches_exhaustive_small_distributions(self):
        for weights, totals in (({'a': 1, 'b': 2}, [1, 3, 1]),
                                ({'a': 2, 'b': 3, 'c': 5}, [0, 2, 4, 2]),
                                ({'a': 1}, [0, 3])):
            with self.subTest(weights=weights):
                expected = 0
                for total in totals:
                    expected += min(sum(abs(counts[i] * b - counts[j] * a)
                                        for i, a in enumerate(weights.values())
                                        for j, b in enumerate(weights.values()) if j > i)
                                    for counts in itertools.product(range(total + 1), repeat=len(weights))
                                    if sum(counts) == total)
                # R2 and R4 remainder minima remain separate from R5 weights.
                year_totals = [(4, [1, 3]), (2, [1]), (0, [0])]
                model, objective, variables = _posting_balance_relaxation(year_totals, totals, weights)
                model.minimize(objective)
                solver = cp_model.CpSolver()
                self.assertEqual(solver.solve(model), cp_model.OPTIMAL)
                self.assertEqual(solver.value(objective), expected + 7)
                self.assertEqual(len(variables), len(set(totals)) * len(weights))

    def test_block_bound_projects_exact_choices_and_preserves_request_flags(self):
        def options(key):
            return [{'requirement_id': key, 'institution': site, 'label': f'{site} {key}'}
                    for site in ('A', 'B')]
        def block(key, length, partial=False):
            return ({'requirement_id': key, 'remaining_months': length}, options(key), partial)
        people = [{'availability': [{'available': m != 1} for m in range(5)]}]
        candidates = [[{'credited_r1_months': 12}]]
        years = ([[block('r2.a', 1, True), block('r2.b', 2)]], [[]],
                 [[block('r4.a', 1), block('r4.b', 1)]], [[]])
        original_flag = cp_model.CpModel().new_bool_var('full_request_flag')
        outcomes = [[{'status': 'evaluable', 'starts': [2],
                      'option_keys': [('r2.b', 'A', 'A r2.b')], '_flag': original_flag}]]
        data = (people, candidates, years, outcomes)
        year_totals = [(2, [1, 0, 1, 1, 0]), (2, [0, 0, 0, 0, 1])]
        model, objective, variables = _posting_block_relaxation(data, year_totals, 3, 0)
        model.minimize(objective)
        solver = cp_model.CpSolver()
        self.assertEqual(solver.solve(model), cp_model.OPTIMAL)
        # One resident contributes one imbalance per active training month;
        # R4's unfinished block carries beyond the horizon. R5 bound adds 3.
        self.assertEqual(solver.value(objective), 7)
        self.assertIs(outcomes[0][0]['_flag'], original_flag)
        # A is not the last institution variant, so it survives only when the
        # request signature is respected during deduplication.
        full = cp_model.CpModel()
        actual_solve = cp_model.CpSolver.solve
        def timeout_blocks(solver, tested_model, *args, **kwargs):
            if any(v.name.startswith('r2.a') for v in tested_model.proto.variables):
                return cp_model.UNKNOWN
            return actual_solve(solver, tested_model, *args, **kwargs)
        with patch.object(cp_model.CpSolver, 'solve', timeout_blocks):
            _, status, stages, _ = _solve_priorities(full, [
                ('resident_requests', 0), ('posting_balance', 7)
            ], [], 20, posting_balance_data=(year_totals, [1], {'a': 3, 'b': 3}),
                posting_block_data=data)
        self.assertEqual(status, 'optimal')
        self.assertEqual(stages[-1]['posting_relaxation']['lower_bound'], 7)
        self.assertIsNone(stages[-1]['posting_relaxation']['block_lower_bound'])
        self.assertIs(outcomes[0][0]['_flag'], original_flag)

    def test_r5_totals_with_loa_partial_demand_or_mixed_year_progression(self):
        for partial in (False, True):
            with self.subTest(partial=partial):
                book = r5_book()
                for sheet in book["annual_sheets"]:
                    for past in sheet["residents"]:
                        if past is not book["residents"][0]:
                            for month in past["postings"]:
                                month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
                if partial:
                    book["annual_sheets"].append({"residents": [resident(
                        [("2027-06", "IMH Geriatric Psychiatry")], "R5", "Partial R5")]})
                    expected_totals = [1, 0] + [1] * 10
                    expected_weights = {'r5.geriatric_psychiatry': 2,
                                        'r5.child_adolescent_psychiatry': 3, 'r5.elective': 6}
                else:
                    for month in book["annual_sheets"][-1]["residents"][0]["postings"][-3:]:
                        month.update(status="loa", value="LOA")
                    book["residents"][0]["residency_year"] = "R4,R5"
                    expected_totals = [0] * 4 + [1] * 8
                    expected_weights = {'r5.geriatric_psychiatry': 1,
                                        'r5.child_adolescent_psychiatry': 1, 'r5.elective': 2}
                book["residents"][0]["postings"][1].update(status="loa", value="LOA")
                original = deepcopy(book)
                with patch('scheduler._posting_balance_relaxation', wraps=_posting_balance_relaxation) as relaxation:
                    result = draft_schedule(book, STORE, max_seconds=30)
                self.assertEqual(result['status'], 'optimal', result['blockers'])
                year_totals, totals, weights = relaxation.call_args.args
                self.assertEqual(totals, expected_totals)
                self.assertEqual(weights, expected_weights)
                person = result['residents'][0]
                if partial:
                    self.assertEqual([person['months'][i]['label'] for i in (0, 2)],
                                     ['IMH Geriatric Psychiatry'] * 2)
                else:
                    self.assertEqual(next(t for k, t in year_totals if k == 1), [1, 0, 1, 1] + [0] * 8)
                    self.assertEqual([person['months'][i]['target']['requirement_id'] for i in (0, 2, 3)],
                                     ['r4.forensic_psychiatry'] * 3)
                expected = 0
                for month in range(12):
                    counts = Counter(p['months'][month]['target']['requirement_id']
                                     for p in result['residents'] if p['months'][month]['target'])
                    expected += sum(abs(counts[a] * weights[b] - counts[b] * weights[a])
                                    for i, a in enumerate(weights) for b in list(weights)[i + 1:])
                self.assertEqual(result['soft_results']['posting_balance'], expected)
                self.assertEqual(book, original)

    def test_full_restrictions_and_priority_locks_survive_bound_or_timeout(self):
        actual_solve = cp_model.CpSolver.solve
        data = ([(2, [1])], [1], {'a': 1, 'b': 2})
        for outcome in ("optimal", "unknown", "feasible"):
            with self.subTest(outcome=outcome):
                model = cp_model.CpModel()
                x = model.new_bool_var('full_choice')
                model.add(x == 1)  # Stand-in for a compulsory full-model restriction.
                small_solvers = set()
                actual_bound = cp_model.CpSolver.best_objective_bound.fget
                def solve(solver, tested_model, *args, **kwargs):
                    small = any(v.name.startswith('posting_count_') for v in tested_model.proto.variables)
                    if small and outcome == 'unknown':
                        return cp_model.UNKNOWN
                    status = actual_solve(solver, tested_model, *args, **kwargs)
                    if small and outcome == 'feasible':
                        small_solvers.add(solver)
                        return cp_model.FEASIBLE
                    return status
                def certified_bound(solver):
                    return 1.9 if solver in small_solvers else actual_bound(solver)
                with patch.object(cp_model.CpSolver, 'solve', solve), patch.object(
                        cp_model.CpSolver, 'best_objective_bound', property(certified_bound)):
                    solver, status, stages, elapsed = _solve_priorities(model, [
                        ('higher', x), ('posting_balance', x + 4), ('later', 1 - x)
                    ], [x], 20, posting_balance_data=data)
                self.assertEqual(status, 'optimal')
                self.assertEqual([s['score'] for s in stages], [1, 5, 0])
                relaxation = stages[1]['posting_relaxation']
                self.assertEqual(relaxation['lower_bound'], {'unknown': None, 'feasible': 1, 'optimal': 2}[outcome])
                self.assertGreaterEqual(stages[1]['wall_time_seconds'], relaxation['wall_time_seconds'])
                self.assertGreaterEqual(stages[1]['best_score_time_seconds'], relaxation['wall_time_seconds'])
                self.assertGreaterEqual(elapsed, sum(s['wall_time_seconds'] for s in stages))
        cancel = Event()
        cancel.set()
        with self.assertRaises(DraftCancelled):
            _solve_priorities(cp_model.CpModel(), [('posting_balance', 0)], [], 20,
                              cancel, posting_balance_data=data)


if __name__ == '__main__':
    unittest.main()
