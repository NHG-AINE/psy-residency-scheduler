import unittest
from ortools.sat.python import cp_model
from request_preferences import period_starts, resolve_requests, add_request_objective


class RequestPreferenceTests(unittest.TestCase):
    def test_periods(self):
        months = [{'month': f'{y}-{m:02d}'} for y, m in [(2027, m) for m in range(7, 13)] + [(2028, m) for m in range(1, 7)]]
        self.assertEqual(period_starts('Jan - June 2028', months, 3), [6, 9])
        self.assertEqual(period_starts('Oct 2027 - Mar 2028', months, 3), [3, 6])
        self.assertEqual(period_starts('Jul - Nov 2027', months, 3), [0])
        self.assertIsNone(period_starts('Jan - Mar 2029', months, 3))
        self.assertEqual(period_starts('Jul - Sep 2027', months, 6), [])

    def test_matching_and_full_placement(self):
        months = [{'month': f'2027-{m:02d}'} for m in range(7, 10)]
        source = {'sheet': 'AY', 'row': 2}
        person = {'source': source, 'recorded_years': ['r2'], 'requirements': [{'requirement_id': 'r2.child', 'requirement_year': 'R2', 'required_months': 3, 'remaining_months': 3}]}
        option = {'valid': True, 'requirement_id': 'r2.child', 'posting': 'Child Psychiatry', 'label': 'IMH Child Psychiatry', 'institution': 'IMH', 'category': 'core', 'residency_year': 'R2'}
        row = {'matched_resident_source': source, 'posting_request': '  child   psychiatry ', 'period': None}
        outcomes = resolve_requests(person, [row, row], [option], months)
        self.assertEqual(outcomes[0]['status'], 'evaluable')
        self.assertEqual(outcomes[1]['duplicate_of'], 0)
        model = cp_model.CpModel()
        v = model.new_bool_var('placement')
        model.add(v == 1)
        objective = add_request_objective(model, [outcomes], [[{'variable': v, 'option': option, 'months': [0, 1], 'remaining': 1}]])
        model.minimize(objective)
        solver = cp_model.CpSolver()
        solver.solve(model)
        self.assertEqual(solver.value(objective), 1)
        ambiguous = dict(option, category='elective')
        self.assertEqual(resolve_requests(person, [row], [option, ambiguous], months)[0]['status'], 'evaluable')
        self.assertEqual(resolve_requests(person, [row], [ambiguous], months)[0]['status'], 'pending')
        elective_row = dict(row, posting_request='Child Psychiatry (eLeCtIvE)')
        self.assertEqual(resolve_requests(person, [elective_row], [ambiguous], months)[0]['option_keys'], [('r2.child', 'IMH', 'IMH Child Psychiatry')])
        core_row = dict(row, posting_request='Child Psychiatry (Core)')
        self.assertEqual(resolve_requests(person, [core_row], [option, ambiguous], months)[0]['status'], 'evaluable')

    def test_recorded_year_precedes_earlier_requirement(self):
        months = [{'month': f'2027-{m:02d}'} for m in range(7, 10)]
        source = {'sheet': 'AY', 'row': 2}
        person = {'source': source, 'recorded_years': ['r5'], 'requirements': [
            {'requirement_id': f'r{y}.elective', 'requirement_year': f'R{y}', 'required_months': 3 if y == 2 else 6, 'remaining_months': 3 if y == 2 else 6}
            for y in (2, 5)]}
        early = {'valid': True, 'requirement_id': 'r2.elective', 'posting': 'ANDS', 'label': 'IMH ANDS', 'institution': 'IMH', 'category': 'elective', 'residency_year': 'R2'}
        current = dict(early, requirement_id='r5.elective', residency_year='R5')
        row = {'matched_resident_source': source, 'posting_request': 'IMH ANDS (Elective)', 'period': None}
        self.assertEqual(resolve_requests(person, [row], [early, current], months)[0]['requirement_id'], 'r5.elective')
        person['requirements'][0]['remaining_months'] = 0
        self.assertEqual(resolve_requests(person, [row], [early], months)[0]['status'], 'pending')
        other = dict(current, posting='Other', label='IMH Other')
        competing = [row, dict(row, posting_request='IMH Other (Elective)')]
        self.assertEqual([item['status'] for item in resolve_requests(person, competing, [current, other], months)], ['pending', 'pending'])





if __name__ == '__main__':
    unittest.main()
