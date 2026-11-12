import unittest
from ortools.sat.python import cp_model
from request_preferences import period_starts, resolve_requests, add_request_objective, unmet_request_reason


class RequestPreferenceTests(unittest.TestCase):
    def test_reason_distinguishes_proven_restrictions_from_search_outcomes(self):
        req = {'requirement_id': 'r2.child', 'requirement_year': 'R2', 'posting': 'Child Psychiatry', 'remaining_months': 3, 'expected_months': 0}
        person = {'requirements': [req], 'months': [], 'availability': [{'available': True}] * 3}
        option = {'requirement_id': 'r2.child', 'institution': 'IMH', 'posting': 'Child', 'label': 'IMH Child', 'capacity': 1}
        request = {'requirement_id': 'r2.child', 'option_keys': [('r2.child', 'IMH', 'IMH Child')], 'starts': [0]}
        placement = {'option': option, 'months': [0, 1, 2]}
        for stages, code in (([], 'request_search_incomplete'),
                             ([{'priority': 'resident_requests', 'status': 'feasible'}], 'request_search_incomplete'),
                             ([{'priority': 'resident_requests', 'status': 'optimal'}], 'not_selected')):
            with self.subTest(stages=stages):
                reason_code, message = unmet_request_reason(person, request, [placement], [option], stages)
                self.assertEqual(reason_code, code)
                self.assertNotIn('capacity', message.lower())  # Capacity 1 alone does not establish why it lost.
        request.update(starts=[], duration=3, period_months=[0, 1], request={'period': 'Jul - Aug 2027'})
        self.assertEqual(unmet_request_reason(person, request, [], [option], []),
                         ('no_valid_start', 'R2 Child Psychiatry requires 3 months, but the requested Jul - Aug 2027 period is only 2 months.'))
        req['remaining_months'] = 0
        self.assertEqual(unmet_request_reason(person, request, [], [option], [])[0], 'requirement_completed')

    def test_periods(self):
        months = [{'month': f'{y}-{m:02d}'} for y, m in [(2027, m) for m in range(7, 13)] + [(2028, m) for m in range(1, 7)]]
        self.assertEqual(period_starts('Jan - June 2028', months, 3), [6, 9])
        self.assertEqual(period_starts('Oct 2027 - Mar 2028', months, 3), [3, 6])
        self.assertEqual(period_starts('Jul - Nov 2027', months, 3), [0])
        self.assertIsNone(period_starts('Jan - Mar 2029', months, 3))
        self.assertEqual(period_starts('Jul - Sep 2027', months, 6), [])
        self.assertEqual(period_starts(None, months, 12), list(range(12)))
        self.assertEqual(period_starts('Jan - June 2028', months, 12), [6])
        self.assertEqual(period_starts('Apr - June 2028', months, 6), [9])

    def test_matching_and_valid_start(self):
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
        self.assertEqual(solver.value(objective), 0)
        ambiguous = dict(option, category='elective')
        self.assertEqual(resolve_requests(person, [row], [option, ambiguous], months)[0]['status'], 'evaluable')
        self.assertEqual(resolve_requests(person, [row], [ambiguous], months)[0]['status'], 'evaluable')
        elective_row = dict(row, posting_request='Child Psychiatry (eLeCtIvE)')
        self.assertEqual(resolve_requests(person, [elective_row], [ambiguous], months)[0]['option_keys'], [('r2.child', 'IMH', 'IMH Child Psychiatry')])
        core_row = dict(row, posting_request='Child Psychiatry (Core)')
        self.assertEqual(resolve_requests(person, [core_row], [option, ambiguous], months)[0]['status'], 'evaluable')
        self.assertEqual(resolve_requests(person, [core_row], [ambiguous], months)[0]['status'], 'pending')
        self.assertEqual(resolve_requests(person, [elective_row], [option], months)[0]['status'], 'pending')

    def test_unmarked_requests_prefer_only_unfinished_requirements(self):
        months = [{'month': f'2027-{m:02d}'} for m in range(7, 10)]
        source = {'sheet': 'AY', 'row': 2}
        core = {'requirement_id': 'r2.addiction_medicine', 'requirement_year': 'R2',
                'required_months': 3, 'remaining_months': 0}
        elective = dict(core, requirement_id='r2.elective', remaining_months=3)
        person = {'source': source, 'recorded_years': ['r2'], 'requirements': [core, elective]}
        option = {'valid': True, 'requirement_id': core['requirement_id'], 'posting': 'Addiction Medicine',
                  'label': 'IMH Addiction Medicine', 'institution': 'IMH', 'category': 'core', 'residency_year': 'R2'}
        options = [option, dict(option, requirement_id=elective['requirement_id'], category='elective')]
        row = {'matched_resident_source': source, 'posting_request': 'IMH Addiction Medicine', 'period': None}
        for core_remaining, elective_remaining, marker, expected in (
                (0, 3, '', 'r2.elective'),
                (3, 3, '', 'r2.addiction_medicine'),
                (0, 3, ' (Core)', 'r2.addiction_medicine'),
                (3, 3, ' (Elective)', 'r2.elective'),
                (0, 0, '', 'r2.addiction_medicine')):
            with self.subTest(core=core_remaining, elective=elective_remaining, marker=marker):
                core['remaining_months'], elective['remaining_months'] = core_remaining, elective_remaining
                request = dict(row, posting_request=row['posting_request'] + marker)
                outcome = resolve_requests(person, [request], options, months)[0]
                self.assertEqual(outcome['status'], 'evaluable')
                self.assertEqual(outcome['requirement_id'], expected)
                self.assertEqual({key[0] for key in outcome['option_keys']}, {expected})
                if not next(req for req in person['requirements'] if req['requirement_id'] == expected)['remaining_months']:
                    self.assertEqual(unmet_request_reason(person, outcome, [], options, [])[0], 'requirement_completed')
        # A completed elective in the recorded year must not hide an unfinished earlier elective.
        elective['remaining_months'] = 3
        later = dict(elective, requirement_id='r5.elective', requirement_year='R5', required_months=6, remaining_months=0)
        person['requirements'].append(later)
        person['recorded_years'] = ['r5']
        options.append(dict(options[1], requirement_id='r5.elective', residency_year='R5'))
        self.assertEqual(resolve_requests(person, [row], options, months)[0]['requirement_id'], 'r2.elective')
        later['remaining_months'] = 6
        person['recorded_years'] = ['r2', 'r5']
        self.assertEqual(resolve_requests(person, [row], options, months)[0]['reason'], 'No unique eligible catalogue posting')

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
