import unittest
from copy import deepcopy
from ortools.sat.python import cp_model
from request_preferences import add_request_objective
from scheduler import _solve_priorities, draft_schedule
from tests.test_r2_rules import r2_book
from tests.test_r3_rules import r3_book
from tests.test_requirement_ledger import resident
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
                outcome = result['residents'][0]['requests'][0]
                self.assertEqual(outcome['status'], expected)
                if scenario in ('capacity', 'loa', 'mixed'):
                    self.assertEqual(outcome['reason_code'], {'capacity': 'zero_capacity', 'loa': 'loa_start', 'mixed': 'training_progression'}[scenario])
                elif scenario == 'met':
                    self.assertIsNone(outcome['reason'])
                else:
                    self.assertEqual(outcome['reason'], 'No unique eligible catalogue posting')
                priorities = result['soft_priority']
                if scenario == 'pending':
                    self.assertNotIn('resident_requests', priorities)
                else:
                    self.assertEqual(priorities.index('resident_requests'), 2)
                    stage = next(stage for stage in result['optimisation_stages'] if stage['priority'] == 'resident_requests')
                    self.assertEqual(stage['score'], 0 if scenario == 'met' else 1)

    def test_mixed_year_clinic_start_fulfils_request_without_completing_training(self):
        for scenario in ('blank', 'explicit', 'loa', 'wrong_start', 'wrong_institution'):
            with self.subTest(scenario=scenario):
                book = r3_book(complete_r2=False)
                person = book['residents'][0]
                person['residency_year'] = 'R2,R3'
                past = resident([(f'2026-{7+i:02d}', label) for i, label in enumerate(
                    ['IMH Geriatric Psychiatry'] * 3 + ['IMH Child & Adolescent Psychiatry'] * 3)],
                    'R2', 'R2 history', person['source']['row'])
                past.update(name=person['name'], mcr=person['mcr'])
                book['annual_sheets'].append({'residents': [past]})
                period = 'Jul - Dec 2027' if scenario == 'wrong_start' else 'Jan - June 2028' if scenario == 'explicit' else None
                book['requests'] = [{'posting_request': 'NTFGH Continuity Clinic', 'period': period,
                    'source': {'sheet': 'Request', 'row': 2}, 'matched_resident_source': person['source']}]
                if scenario == 'loa':
                    person['postings'][7].update(status='loa', value='LOA')
                if scenario == 'wrong_institution':
                    next(o for o in book['postings']['core'] if o['posting'] == 'NTFGH Continuity Clinic')['max'] = 0
                original = deepcopy(book)
                result = draft_schedule(book, STORE, max_seconds=20)
                self.assertIn(result['status'], {'optimal', 'feasible'}, result['blockers'])
                planned = result['residents'][0]
                outcome = planned['requests'][0]
                met = scenario not in ('wrong_start', 'wrong_institution')
                self.assertEqual(outcome['status'], 'met' if met else 'not_met')
                stage = next(s for s in result['optimisation_stages'] if s['priority'] == 'resident_requests')
                self.assertEqual(stage['score'], 0 if met else 1)
                clinic = [m for m in planned['months'] if (m.get('target') or {}).get('requirement_id') == 'r3.continuity_clinic']
                self.assertEqual(clinic[0]['month'], '2028-01')
                self.assertEqual(sum(c['months'] for c in planned['carryforward']), 7 if scenario == 'loa' else 6)
                self.assertEqual(outcome['matched_months'], [m['month'] for m in clinic] if met else [])
                if met:
                    self.assertTrue(all(m['label'] == 'NTFGH Continuity Clinic' for m in clinic))
                    self.assertEqual(outcome['replacement_months'], [])
                if scenario == 'loa':
                    self.assertEqual(planned['months'][7]['status'], 'loa')
                    self.assertNotIn('2028-02', outcome['matched_months'])
                self.assertEqual(book, original)
