import unittest
from ortools.sat.python import cp_model
from request_preferences import add_request_objective
from scheduler import _solve_priorities, draft_schedule
from tests.test_r2_rules import r2_book
from tests.test_r1_solver import STORE


class RequestSchedulerTests(unittest.TestCase):
    def test_equal_resident_weight_and_capacity(self):
        model = cp_model.CpModel()
        variables = [model.new_bool_var(f'p{i}') for i in range(3)]
        model.add(sum(variables) <= 1)
        option = {'requirement_id': 'x', 'institution': 'IMH', 'label': 'IMH X'}
        def row():
            return {'status': 'evaluable', 'option_keys': [('x', 'IMH', 'IMH X')], 'duration': 3, 'starts': [0]}
        outcomes = [[row(), row()], [row()]]
        placements = [[{'variable': variables[0], 'option': option, 'months': [0, 1, 2], 'remaining': 0},
                       {'variable': variables[1], 'option': option, 'months': [0, 1, 2], 'remaining': 0}],
                      [{'variable': variables[2], 'option': option, 'months': [0, 1, 2], 'remaining': 0}]]
        # Separate requirements in real placements cannot both be selected for one request.
        outcomes[0][0]['option_keys'] = [('a', 'IMH', 'IMH X')]
        placements[0][0]['option'] = dict(option, requirement_id='a')
        outcomes[0][1]['option_keys'] = [('b', 'IMH', 'IMH X')]
        placements[0][1]['option'] = dict(option, requirement_id='b')
        objective = add_request_objective(model, outcomes, placements)
        solver, status, stages, _ = _solve_priorities(model, [('requests', objective), ('later', variables[2])], variables, 5)
        self.assertEqual(status, 'optimal')
        self.assertEqual(solver.value(variables[2]), 1)
        self.assertEqual(stages[0]['score'], 2)


    def test_actual_draft_respects_request_and_hard_constraints(self):
        for scenario in ('met', 'capacity', 'loa', 'mixed', 'pending'):
            with self.subTest(scenario=scenario):
                book = r2_book(mixed=scenario == 'mixed')
                source = book['residents'][0]['source']
                book['requests'] = [{'posting_request': 'IMH ANDS (Elective)' if scenario != 'pending' else 'Unknown posting',
                                     'period': 'Jul - Sep 2027', 'source': {'sheet': 'Request', 'row': 2},
                                     'matched_resident_source': source}]
                if scenario == 'capacity':
                    book['postings']['electives'][0]['max'] = 0
                if scenario == 'loa':
                    book['residents'][0]['postings'][0].update(status='loa', value='LOA')
                result = draft_schedule(book, STORE, max_seconds=20)
                self.assertIn(result['status'], {'optimal', 'feasible'}, result['blockers'])
                expected = 'met' if scenario == 'met' else 'pending' if scenario == 'pending' else 'not_met'
                self.assertEqual(result['residents'][0]['requests'][0]['status'], expected)
                priorities = result['soft_priority']
                if scenario == 'pending':
                    self.assertNotIn('resident_requests', priorities)
                else:
                    self.assertEqual(priorities.index('resident_requests'), 2)
                    stage = next(stage for stage in result['optimisation_stages'] if stage['priority'] == 'resident_requests')
                    self.assertEqual(stage['score'], 0 if scenario == 'met' else 1)
