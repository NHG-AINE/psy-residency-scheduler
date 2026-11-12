import unittest
from copy import deepcopy
from ortools.sat.python import cp_model
from request_preferences import add_request_objective
from scheduler import _solve_priorities, draft_schedule
from tests.test_r2_rules import r2_book
from tests.test_r3_rules import r3_book
from tests.test_r5_rules import r5_book
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


    def test_short_request_window_still_marks_the_overlapping_assigned_elective(self):
        book = r5_book()
        book['postings']['electives'][-1]['remarks'] = [{'text': '(all required 6 months duration)'}]
        source = book['residents'][0]['source']
        book['requests'] = [
            {'posting_request': label, 'period': period, 'matched_resident_source': source,
             'source': {'sheet': 'Request', 'row': index + 2}}
            for index, (label, period) in enumerate([
                ('IMH Geriatric Psychiatry', 'Jul - Sep 2027'),
                ('IMH Child & Adolescent Psychiatry', 'Oct - Dec 2027'),
                ('IMH Forensic Psychiatry (Elective)', 'Jan - Mar 2028'),
            ])]
        result = draft_schedule(book, STORE, max_seconds=20)
        outcomes = result['residents'][0]['requests']
        self.assertEqual([o['status'] for o in outcomes], ['met', 'met', 'not_met'])
        elective = outcomes[-1]
        self.assertEqual(elective['reason_code'], 'no_valid_start')
        self.assertEqual(elective['reason'], 'R5 Elective requires 6 months, but the requested Jan - Mar 2028 period is only 3 months.')
        self.assertEqual(elective['starts'], [])
        self.assertEqual(elective['matched_months'], [])
        self.assertEqual(elective['replacement_months'], [f'2028-{m:02d}' for m in range(1, 7)])


    def test_r5_two_requested_electives_are_distinct_three_month_blocks(self):
        canonical = "Adult Neurodevelopmental Disorders Service (ANDS)"
        book = r5_book()
        for index, service in enumerate((canonical, "General Psychiatry")):
            book["postings"]["electives"].append({"residency_year": "R5", "institution": "IMH",
                "elective": service, "remarks": ([{"text": "(Team-based continuity of care)"}] if service == "General Psychiatry" else []),
                "max": "1", "source": {"sheet": "Postings", "row": 910 + index}})
        source = book["residents"][0]["source"]
        book["requests"] = [{"posting_request": label, "period": period, "matched_resident_source": source}
                            for label, period in (("IMH Geriatric Psychiatry", "Jul - Sep 2027"),
                                                  ("IMH Child & Adolescent Psychiatry", "Oct - Dec 2027"),
                                                  ("IMH " + canonical + " (Elective)", "Jan - Mar 2028"),
                                                  ("IMH General Psychiatry (East)", "Apr - Jun 2028"))]
        book["requests"].append(deepcopy(book["requests"][2]))
        before = deepcopy(book)
        result = draft_schedule(book, STORE, max_seconds=10)
        self.assertIn(result["status"], {"optimal", "feasible"}, result)
        outcomes = result["residents"][0]["requests"]
        self.assertEqual([o["status"] for o in outcomes], ["met"] * 5)
        self.assertEqual(outcomes[-1]["duplicate_of"], 2)
        self.assertEqual(outcomes[2]["duration_starts"], {3: [6], 6: []})
        self.assertEqual(outcomes[2]["matched_months"], [f"2028-{m:02d}" for m in (1, 2, 3)])
        self.assertEqual(outcomes[3]["matched_months"], [f"2028-{m:02d}" for m in (4, 5, 6)])
        months = result["residents"][0]["months"]
        self.assertEqual([m["label"] for m in months[6:9]], ["IMH " + canonical] * 3)
        self.assertEqual([m["label"] for m in months[9:]], ["IMH General Psychiatry"] * 3)
        self.assertEqual(sum(m["target"]["requirement_id"] == "r5.elective" for m in months), 6)
        self.assertEqual(next(s["score"] for s in result["optimisation_stages"] if s["priority"] == "resident_requests"), 0)
        self.assertEqual(book, before)
        # One three-month request also permits a free choice of the remaining block.
        single = deepcopy(before)
        single["requests"] = single["requests"][:3]
        single_result = draft_schedule(single, STORE, max_seconds=10)
        self.assertIn(single_result["status"], {"optimal", "feasible"}, single_result)
        person = single_result["residents"][0]
        self.assertEqual(person["requests"][2]["status"], "met")
        self.assertEqual(person["requests"][2]["matched_months"], [f"2028-{m:02d}" for m in (1, 2, 3)])
        self.assertEqual(sum(m["target"]["requirement_id"] == "r5.elective" for m in person["months"]), 6)
        # Requested elective preferences still cannot bypass capacity.
        book["postings"]["electives"][-1]["max"] = "0"
        result = draft_schedule(book, STORE, max_seconds=10)
        self.assertEqual(result["residents"][0]["requests"][3]["status"], "not_met")
        self.assertEqual(result["residents"][0]["requests"][3]["reason_code"], "zero_capacity")

    def test_r5_blank_request_is_one_score_when_both_three_month_blocks_match(self):
        from rules.r5_rules import elective_routes, add_routes
        from request_preferences import resolve_requests, placement_fulfils_request
        source = {"sheet": "Planning", "row": 3}
        person = {"source": source, "months": [], "recorded_years": ["r5"],
                  "availability": [{"available": True}] * 12,
                  "requirements": [{"requirement_id": "r5.elective", "requirement_year": "R5",
                                    "required_months": 6, "expected_months": 0, "remaining_months": 6}]}
        option = {"valid": True, "category": "elective", "residency_year": "R5", "requirement_id": "r5.elective",
                  "posting": "A", "institution": "IMH", "label": "IMH A", "remarks": []}
        errors = []
        routes = elective_routes(person, [option], "2027-07", 0, errors, allow_split=True)
        self.assertFalse(errors)
        model = cp_model.CpModel()
        placements = add_routes(model, person, [routes[1]], 0, 0)
        months = [{"month": f"2027-{m:02d}"} for m in range(7, 13)]
        request = {"posting_request": "IMH A", "period": None, "matched_resident_source": source}
        outcomes = resolve_requests(person, [request, request], [option], months)
        objective = add_request_objective(model, [outcomes], [placements])
        self.assertEqual(model.validate(), "")
        model.minimize(objective)
        solver = cp_model.CpSolver()
        self.assertEqual(solver.solve(model), cp_model.OPTIMAL)
        self.assertEqual(solver.value(objective), 0)
        chosen = [p for p in placements if solver.value(p["variable"])]
        self.assertEqual(len(chosen), 2)
        self.assertEqual(sorted(len(p["months"]) for p in chosen), [3, 3])
        self.assertEqual(outcomes[1]["duplicate_of"], 0)
        narrow = resolve_requests(person, [dict(request, period="Jul - Sep 2027")], [option], months)[0]
        six = {"option": option, "months": list(range(6)), "remaining": 0, "block_duration": 6}
        self.assertFalse(placement_fulfils_request(six, narrow))
        late = resolve_requests(person, [dict(request, period="Oct - Dec 2027")], [option], months)[0]
        carry = {"option": option, "months": [3, 4, 5], "remaining": 3, "block_duration": 6}
        self.assertTrue(placement_fulfils_request(carry, late))
        windows = resolve_requests(person, [dict(request, period="Jul - Sep 2027"),
                                            dict(request, period="Jul - Oct 2027")], [option], months)
        self.assertEqual(windows[0]["duration_starts"], windows[1]["duration_starts"])
        self.assertNotIn("duplicate_of", windows[1])
        paused = {"option": option, "months": [0, 1, 3], "remaining": 0, "block_duration": 3}
        self.assertFalse(placement_fulfils_request(paused, windows[0]))
        self.assertTrue(placement_fulfils_request(paused, windows[1]))

    def test_same_site_allocation_counts_a_visit_equally_for_six_or_three_plus_three(self):
        from unittest.mock import patch
        from rules import r5_rules
        original = r5_rules.prepare_routes
        scores = []
        for split in (False, True):
            book = r5_book()
            book["postings"]["electives"].append({**book["postings"]["electives"][-1],
                "institution": "TTSH", "source": {"sheet": "Postings", "row": 920}})
            source = book["residents"][0]["source"]
            periods = ["Jan - Mar 2028", "Apr - Jun 2028"] if split else ["Jan - Jun 2028"]
            pairs = [("IMH Geriatric Psychiatry", "Jul - Sep 2027"),
                     ("IMH Child & Adolescent Psychiatry", "Oct - Dec 2027")]
            pairs += [("TTSH Forensic Psychiatry", period) for period in periods]
            book["requests"] = [{"posting_request": label, "period": period, "matched_resident_source": source}
                                for label, period in pairs]
            def selected_routes(*args):
                return [route for route in original(*args)
                        if sum(r["requirement_id"] == "r5.elective" for r, _, _ in route) == (2 if split else 1)]
            with patch.object(r5_rules, "prepare_routes", side_effect=selected_routes):
                result = draft_schedule(book, STORE, max_seconds=10)
            self.assertIn(result["status"], {"optimal", "feasible"}, result)
            self.assertTrue(all(o["status"] == "met" for o in result["residents"][0]["requests"]))
            self.assertEqual([m["label"] for m in result["residents"][0]["months"][6:]], ["TTSH Forensic Psychiatry"] * 6)
            scores.append(result["soft_results"]["r5_allocation_deviation"])
        self.assertEqual(scores, [2, 2])
