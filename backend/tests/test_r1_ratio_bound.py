"""Check the relaxation against exhaustive small cases, not a workbook score."""
import itertools
import unittest
from copy import deepcopy
from unittest.mock import patch

from ortools.sat.python import cp_model
from rules import r1_rules as r1
from scheduler import _solve_priorities

M = r1.R1['General Medicine']['id']
N = r1.R1['Neurology']['id']
I = r1.R1['Inpatient Psychiatry']['id']


def choice(route, months, site='IMH'):
    return {'route': route, 'schedule': [
        {'requirement_id': requirement, 'institution': site if requirement == I else 'SGH'}
        if requirement else None for requirement in months]}


class RatioRelaxationTests(unittest.TestCase):
    def test_bound_matches_enumeration_with_loa_carryover_and_combined_choices(self):
        paired = [choice(route, months) for route in r1.PAIRED_ROUTES
                  for months in ([M, M, N, N, M, M], [N, N, M, M, M, M])]
        for candidates, active in (
            ([paired], [True]),
            ([paired, paired], [True, True]),
            ([paired, [choice('SGH', [None, N, N, M, None, M])]], [True, False]),
            ([[choice('NUH', [None] * 6), choice('SGH', [N, N, M, M, M, M])]], [False]),
        ):
            with self.subTest(active=active, people=len(candidates)):
                scores = []
                for selected in itertools.product(*candidates):
                    targets = r1._targets(sum(active))
                    distribution = sum(abs(sum(a and c['route'] == route for a, c in zip(active, selected)) - target)
                                       for route, target in targets.items())
                    ratio = sum(abs(sum(c['route'] == route and c['schedule'][m] is not None
                                        and c['schedule'][m]['requirement_id'] == M for c in selected)
                                    - 2 * sum(c['route'] == route and c['schedule'][m] is not None
                                              and c['schedule'][m]['requirement_id'] == N for c in selected))
                                for route in r1.PAIRED_ROUTES for m in range(6))
                    scores.append((distribution, ratio))
                # Include nonzero route deviations; do not assume all targets were attainable.
                for distribution in {d for d, _ in scores}:
                    model, objective, _ = r1.ratio_relaxation(candidates, active, [{}] * 6, distribution)
                    model.minimize(objective)
                    solver = cp_model.CpSolver()
                    self.assertEqual(solver.solve(model), cp_model.OPTIMAL)
                    self.assertEqual(solver.value(objective), min(r for d, r in scores if d == distribution))

    def test_bound_preserves_full_model_destinations_and_unknown_falls_back(self):
        candidates = [[choice('SGH', [M, N, I], site) for site in ('IMH', 'SGH')]]
        original = deepcopy(candidates)
        small, _, reduced = r1.ratio_relaxation(candidates, [True], [{}] * 3, 2)
        self.assertEqual(len(reduced), 1)
        self.assertEqual(candidates, original)
        actual_solve = cp_model.CpSolver.solve
        for timeout in (False, True):
            with self.subTest(timeout=timeout):
                model = cp_model.CpModel()
                variables = [[model.new_bool_var('full_imh'), model.new_bool_var('full_sgh')]]
                model.add_exactly_one(variables[0])
                model.add(variables[0][0] == 0)  # Full-model capacity still excludes IMH.
                preferences = r1.add_preferences(model, candidates, variables, [True], [{}] * 3)
                def solve(solver, tested_model, *args, **kwargs):
                    if timeout and tested_model.proto.variables[0].name.startswith('ratio_choice_'):
                        return cp_model.UNKNOWN
                    return actual_solve(solver, tested_model, *args, **kwargs)
                with patch.object(cp_model.CpSolver, 'solve', solve):
                    solver, status, stages, total = _solve_priorities(model, [
                        ('incoming_route_distribution', preferences['distribution']),
                        ('monthly_medicine_neurology_ratio', preferences['ratio']),
                        ('later', variables[0][1]),
                    ], variables[0], 20, r1_ratio_data=(candidates, [True], [{}] * 3))
                self.assertEqual(status, 'optimal')
                self.assertEqual([stage['score'] for stage in stages], [2, 3, 1])
                self.assertEqual(solver.value(variables[0][1]), 1)
                bound = stages[1]['ratio_relaxation']
                self.assertEqual(bound['lower_bound'], None if timeout else 3)
                self.assertGreaterEqual(stages[1]['wall_time_seconds'], bound['wall_time_seconds'])
                self.assertGreaterEqual(total, sum(stage['wall_time_seconds'] for stage in stages))


if __name__ == '__main__':
    unittest.main()
