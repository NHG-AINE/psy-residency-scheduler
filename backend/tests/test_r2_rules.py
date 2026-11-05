import unittest

from rules.r2_rules import partial_posting_identity


class PartialR2HistoryTests(unittest.TestCase):
    def test_partial_requires_one_exact_posting_and_institution(self):
        person = {"requirements": [{"requirement_id": "r2.elective", "expected_months": 2, "remaining_months": 1}],
                  "months": [{"status": "expected", "requirement_id": "r2.elective", "posting": "ANDS", "institution": "IMH"}]}
        self.assertEqual(partial_posting_identity(person, "r2.elective"), ("ANDS", "IMH"))
        person["months"].append({"status": "expected", "requirement_id": "r2.elective", "posting": "Emergency Psychiatry", "institution": "IMH"})
        with self.assertRaisesRegex(ValueError, "conflicting_partial_r2_history"):
            partial_posting_identity(person, "r2.elective")
        person["requirements"][0]["remaining_months"] = 0
        self.assertIsNone(partial_posting_identity(person, "r2.elective"))


from collections import Counter
from copy import deepcopy
from programme_requirements import PROGRAMME_REQUIREMENTS
from scheduler import draft_schedule
from tests.test_r1_solver import r1_book, set_history, STORE
from tests.test_requirement_ledger import resident


def r2_book(size=1, mixed=False):
    workbook = r1_book()
    values = ["TTSH General Medicine"] * 4 + ["NNI Neurology"] * 2
    if not mixed:
        values += ["IMH Inpatient Psychiatry"] * 6
    history = set_history(workbook, values)
    for month in history["postings"]:
        month["month"] = month["month"].replace("2026", "2025").replace("2027", "2026")
    workbook["residents"][0]["residency_year"] = "R1,R2" if mixed else "R2"
    for name, rule in PROGRAMME_REQUIREMENTS["R2"].items():
        if name == "Elective":
            continue
        for site in rule["institutions"]:
            workbook["postings"]["core"].append({"residency_year": "R2", "posting": f"{site} {name}",
                "duration_months": str(rule["months"]), "source": {"sheet": "Postings", "row": len(workbook["postings"]["core"]) + 2}})
    workbook["postings"]["electives"] = [{"residency_year": "R2", "institution": "IMH", "elective": title,
        "source": {"sheet": "Postings", "row": 100+i}, "remarks": []} for i,title in enumerate(("ANDS", "Addiction Medicine"))]
    for i in range(1,size):
        person = deepcopy(workbook["residents"][0])
        person.update(name=f"Example {i}", mcr=f"M00{i+1}", source={"sheet":"Planning", "row":i+3})
        for month in person["postings"]:
            month["source"] = {**person["source"], "column":month["source"]["column"]}
        workbook["residents"].append(person)
        past = deepcopy(history)
        past.update(name=person["name"], mcr=person["mcr"], source={"sheet":"History", "row":i+3})
        for month in past["postings"]:
            month["source"] = {**past["source"], "column":month["source"]["column"]}
        workbook["annual_sheets"][0]["residents"].append(past)
    return workbook


class R2SolverTests(unittest.TestCase):
    def solve(self, book):
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result.get("blockers"))
        return result

    def test_full_r2_balances_requirements_in_continuous_blocks_without_mutating_import(self):
        book = r2_book(4)
        before = deepcopy(book)
        result = self.solve(book)
        for person in result["residents"]:
            months = person["months"]
            self.assertEqual(set(Counter(m["target"]["requirement_id"] for m in months).values()), {3})
            for start in range(0,12,3):
                self.assertEqual(len({(m["target"]["requirement_id"],m["label"]) for m in months[start:start+3]}), 1)
            self.assertEqual(person["carryforward"], [])
        self.assertEqual(result["soft_results"]["posting_balance"], 0)
        self.assertEqual(book, before)

    def test_mixed_year_finishes_r1_before_r2_and_carries_remainder(self):
        result = self.solve(r2_book(mixed=True))
        self.assertEqual(len(result["residents"]), 1)
        person = result["residents"][0]
        self.assertTrue(all(m["target"]["requirement_id"] == "r1.inpatient_psychiatry" for m in person["months"][:6]))
        self.assertTrue(all(m["target"]["requirement_id"].startswith("r2.") for m in person["months"][6:]))
        self.assertEqual(sum(c["months"] for c in person["carryforward"]), 6)

    def test_partial_elective_resumes_exact_identity_and_loa_pauses_it(self):
        book = r2_book()
        book["annual_sheets"].insert(1, {"residents":[resident([("2027-06","IMH ANDS (Elective)")], "R2", "Partial")]})
        book["residents"][0]["postings"][1].update(status="loa", value="LOA")
        result = self.solve(book)["residents"][0]
        self.assertEqual([result["months"][i]["label"] for i in (0,2)], ["IMH ANDS"]*2)
        self.assertEqual(result["months"][1]["status"], "loa")
        self.assertEqual(result["carryforward"], [])

    def test_elective_capacity_is_per_catalogue_entry_not_institution_or_core(self):
        book = r2_book(4)
        for elective in book["postings"]["electives"]:
            elective["max"] = 1
        result = self.solve(book)
        for index in range(12):
            counts = Counter(m["label"] for p in result["residents"] for m in [p["months"][index]] if m["target"]["category"] == "elective")
            self.assertTrue(all(n<=1 for n in counts.values()))
        # With only elective work left, distinct same-institution entries can run together.
        for person in book["residents"]:
            past = resident([(f"{2026 + (m+5)//12}-{(m+5)%12+1:02d}",label) for m,label in enumerate(
                ["IMH Geriatric Psychiatry"]*3+["IMH Child & Adolescent Psychiatry"]*3+["IMH Addiction Medicine"]*3,1)], "R2", "R2 history", person["source"]["row"])
            past.update(name=person["name"],mcr=person["mcr"])
            book["annual_sheets"].insert(1,{"residents":[past]})
        book["residents"][:] = book["residents"][:2]
        result = self.solve(book)
        self.assertEqual({p["months"][0]["label"] for p in result["residents"]}, {"IMH ANDS", "IMH Addiction Medicine"})
        for elective in book["postings"]["electives"]:
            elective["max"] = 0
        self.assertEqual(draft_schedule(book,STORE)["status"], "infeasible")

    def test_conflicting_partial_history_and_unsupported_remarks_block(self):
        for kind in ("partial", "remarks", "duplicate", "missing"):
            with self.subTest(kind=kind):
                book = r2_book()
                if kind == "partial":
                    book["annual_sheets"].insert(1,{"residents":[resident([("2027-05","IMH ANDS (Elective)"),("2027-06","IMH Addiction Medicine (Elective)")],"R2","Partial")]})
                    code="conflicting_partial_r2_history"
                elif kind == "remarks":
                    book["postings"]["electives"][0]["remarks"]=[{"text":"Must start in July"}]
                    code="unsupported_r2_remarks"
                elif kind == "duplicate":
                    book["postings"]["electives"].append(deepcopy(book["postings"]["electives"][0]))
                    code="duplicate_r2_catalogue_option"
                else:
                    book["postings"]["electives"]=[]
                    code="missing_r2_catalogue_option"
                result=draft_schedule(book,STORE)
                self.assertEqual(result["status"],"blocked")
                self.assertIn(code,[b["code"] for b in result["blockers"]])


    def test_excluded_year_catalogue_capacity_is_not_pooled_by_label(self):
        book=r2_book()
        book["postings"]["electives"][0]["max"]=1
        book["postings"]["electives"].append({"residency_year":"R5","institution":"IMH","elective":"ANDS",
            "source":{"sheet":"Postings","row":200},"remarks":[]})
        outside=resident([(m["month"],"IMH ANDS (Elective)") for m in book["months"]],"R5","Planning",200)
        outside.update(name="Other resident",mcr="OTHER")
        book["residents"].append(outside)
        result=self.solve(book)
        self.assertEqual(len(result["residents"]),1)
        self.assertEqual(result["excluded_residents"][0]["source"],outside["source"])


class R2BlockBoundaryTests(unittest.TestCase):
    def test_candidates_and_feasible_schedules_match_complete_block_orders(self):
        from itertools import permutations
        from ortools.sat.python import cp_model
        from rules.r2_rules import add_blocks

        for lengths, partial, r1_months, loa in (
                ([3, 3, 3, 3], None, 0, set()),
                ([2, 3, 3, 3], 0, 0, set()),
                ([3, 3, 3, 3], None, 6, set()),
                ([2, 3, 3, 3], 0, 3, {1, 5})):
            with self.subTest(lengths=lengths, partial=partial, r1_months=r1_months, loa=loa):
                active = [i for i in range(12) if i not in loa]
                blocks = [({"requirement_id": str(i), "remaining_months": length},
                           [{"requirement_id": str(i)}], i == partial) for i, length in enumerate(lengths)]
                expected_schedules, expected_candidates = set(), set()
                # Independent reference: enumerate complete posting orders, not
                # candidate start positions. There are at most 24 permutations.
                for order in permutations(range(len(lengths))):
                    if partial is not None and order[0] != partial:
                        continue
                    tick, schedule = r1_months, []
                    for i in order:
                        months = tuple(active[t] for t in range(tick, tick + lengths[i]) if t < len(active))
                        placement = (str(i), months, lengths[i] - len(months))
                        schedule.append(placement)
                        expected_candidates.add(placement)
                        tick += lengths[i]
                    expected_schedules.add(tuple(sorted(schedule)))
                model = cp_model.CpModel()
                placements = add_blocks(model, {"availability": [{"available": i not in loa} for i in range(12)]}, blocks, r1_months, 0)

                def signature(p):
                    return (p["option"]["requirement_id"], tuple(p["months"]), p["remaining"])

                self.assertEqual({signature(p) for p in placements}, expected_candidates)
                class Solutions(cp_model.CpSolverSolutionCallback):
                    def __init__(self):
                        super().__init__()
                        self.schedules = set()

                    def on_solution_callback(self):
                        self.schedules.add(tuple(sorted(signature(p) for p in placements if self.value(p["variable"]))))

                solutions = Solutions()
                solver = cp_model.CpSolver()
                solver.parameters.enumerate_all_solutions = True
                solver.parameters.num_search_workers = 1
                self.assertEqual(solver.solve(model, solutions), cp_model.OPTIMAL)
                self.assertEqual(solutions.schedules, expected_schedules)
