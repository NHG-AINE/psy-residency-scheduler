"""R1 draft checks validate constraints rather than a particular timetable."""
import unittest
from collections import Counter
from copy import deepcopy
from unittest.mock import patch

from ortools.sat.python import cp_model

from history_review import ReviewStore
from programme_requirements import PROGRAMME_REQUIREMENTS
from r1_solver import draft_r1_schedule
from test_requirement_ledger import resident
import test_workbook_import


STORE = ReviewStore(version=1, decisions=[])


def r1_book(size=1):
    workbook = test_workbook_import.IncomingIntakeTests().parse([("New Resident", "NEW", "R1", 2027)])
    workbook["residents"] = workbook["residents"][:size]
    for person in workbook["residents"]:
        for month in person["postings"]:
            month.update(status="blank", value=None)
    workbook["issues"], workbook["requests"] = [], []
    workbook["annual_sheets"] = [{"residents": workbook["residents"]}]
    workbook["histories"] = []
    core = []
    for posting, rule in PROGRAMME_REQUIREMENTS["R1"].items():
        for institution in rule["institutions"]:
            core.append({"residency_year": "R1", "posting": f"{institution} {posting}",
                         "duration_months": str(rule["months"]), "max": None,
                         "remarks": "To be completed in the " + ("second" if posting == "Inpatient Psychiatry" else "first") + " 6 months of R1",
                         "source": {"sheet": "Postings", "row": len(core) + 2}})
    workbook["postings"] = {"core": core, "electives": []}
    return workbook


def set_history(workbook, values):
    person = workbook["residents"][0]
    person.update(name="Alex Example", mcr="M001", intake="2026", residency_year="R1,R2")
    history = resident([(f"{2026 + (i + 6) // 12}-{(i + 6) % 12 + 1:02d}", value) for i, value in enumerate(values)], "R1")
    workbook["annual_sheets"].insert(0, {"residents": [history]})
    return history


class R1SolverTests(unittest.TestCase):
    def check_resident(self, person):
        active = [m for m in person["months"] if m["status"] == "posting"]
        counts = Counter(m["target"]["requirement_id"] for m in active)
        self.assertEqual(len(active), 12)
        self.assertTrue(all(m["target"]["requirement_id"] != "r1.inpatient_psychiatry" for m in active[:6]))
        self.assertTrue(all(m["target"]["requirement_id"] == "r1.inpatient_psychiatry" for m in active[6:]))
        self.assertEqual(len({m["label"] for m in active[6:]}), 1)
        if person["route"] == "NUH":
            self.assertEqual(counts["r1.medicine_neurology"], 6)
            self.assertTrue(all(m["target"]["institution"] == "NUH" for m in active[:6]))
        else:
            self.assertEqual((counts["r1.general_medicine"], counts["r1.neurology"]), (4, 2))
            neuro = [i for i, m in enumerate(active) if m["target"]["requirement_id"] == "r1.neurology"]
            self.assertEqual(neuro[1] - neuro[0], 1)
            pair = {m["target"]["institution"] for m in active[:6]}
            self.assertEqual(pair, {"TTSH", "NNI"} if person["route"] == "TTSH/NNI" else {"SGH"})
        self.assertEqual(person["carryforward"], [])

    def test_full_routes_have_exact_duration_training_windows_pairing_and_labels(self):
        workbook = r1_book(24)
        original = deepcopy(workbook)
        result = draft_r1_schedule(workbook, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"})
        self.assertEqual({p["route"] for p in result["residents"]}, {"TTSH/NNI", "SGH", "NUH"})
        labels = {r["posting"] for r in workbook["postings"]["core"]}
        for person in result["residents"]:
            self.check_resident(person)
            self.assertTrue(all(m["label"] in labels for m in person["months"]))
        self.assertEqual(result["soft_results"]["ratio_deviation"], 0)
        self.assertEqual(workbook, original)

    def test_continuing_history_preserves_pairing_neuro_block_and_only_schedules_remaining(self):
        workbook = r1_book()
        set_history(workbook, ["TTSH General Medicine"] * 2 + ["NNI Neurology"] * 2 + ["TTSH General Medicine"] * 2
                    + ["LOA"] * 3 + ["IMH Inpatient Psychiatry"] * 3)
        result = draft_r1_schedule(workbook, STORE)
        self.assertEqual(result["status"], "optimal")
        person = result["residents"][0]
        self.assertEqual(person["route"], "TTSH/NNI")
        self.assertEqual(person["credited_r1_months"], 9)
        self.assertEqual([m["label"] for m in person["months"][:3]], ["IMH Inpatient Psychiatry"] * 3)
        self.assertTrue(all(m["status"] == "outside_r1_scope" for m in person["months"][3:]))
        self.assertEqual(person["carryforward"], [])
        self.assertEqual(result["soft_targets"]["active_incoming_cohort_size"], 0)
        # Past timing exceptions and blank/missing calendar months do not undo credit.
        for gap in (False, True):
            with self.subTest(historical_gap=gap):
                exceptional = r1_book()
                values = ["SGH General Medicine"] + ["LOA"] * 5 + ["IMH Inpatient Psychiatry"] * 6
                if gap:
                    values[1] = None
                history = set_history(exceptional, values)
                if gap:
                    history["postings"].pop(2)
                    exceptional["residents"][0]["intake"] = None
                original = deepcopy(exceptional)
                draft = draft_r1_schedule(exceptional, STORE)
                self.assertEqual(draft["status"], "optimal")
                person = draft["residents"][0]
                self.assertEqual(person["route"], "SGH")
                self.assertEqual(person["credited_r1_months"], 7)
                self.assertEqual(Counter(m["label"] for m in person["months"] if m["status"] == "posting"),
                                 {"SGH General Medicine": 3, "SGH Neurology": 2})
                self.assertEqual(sum(m["status"] == "outside_r1_scope" for m in person["months"]), 7)
                self.assertEqual(exceptional, original)
        # Cross-pair history still counts; future assignments form one valid pair.
        exceptional = r1_book()
        set_history(exceptional, ["TTSH General Medicine", "SGH Neurology"] + ["IMH Inpatient Psychiatry"] * 6 + [None] * 4)
        person = draft_r1_schedule(exceptional, STORE)["residents"][0]
        future = [m for m in person["months"] if m["status"] == "posting"]
        self.assertEqual(Counter(m["target"]["requirement_id"] for m in future),
                         {"r1.general_medicine": 3, "r1.neurology": 1})
        self.assertIn({m["target"]["institution"] for m in future}, ({"TTSH", "NNI"}, {"SGH"}))
        # Excess credited months and split inpatient sites never create negative remainders.
        exceptional = r1_book()
        set_history(exceptional, ["TTSH General Medicine"] * 5 + ["SGH Neurology"] * 3
                    + ["IMH Inpatient Psychiatry"] * 2 + ["SGH Inpatient Psychiatry"] * 2)
        person = draft_r1_schedule(exceptional, STORE)["residents"][0]
        self.assertEqual(person["credited_r1_months"], 10)
        self.assertEqual(Counter(m["target"]["requirement_id"] for m in person["months"] if m["status"] == "posting"),
                         {"r1.inpatient_psychiatry": 2})
        self.assertEqual(person["carryforward"], [])
        # A completed combined route beats unused alternative requirements.
        exceptional = r1_book()
        set_history(exceptional, ["NUH Medicine & Neurology"] * 6 + ["TTSH General Medicine"] + [None] * 5)
        person = draft_r1_schedule(exceptional, STORE)["residents"][0]
        self.assertEqual(person["route"], "NUH")
        self.assertEqual(Counter(m["target"]["requirement_id"] for m in person["months"] if m["status"] == "posting"),
                         {"r1.inpatient_psychiatry": 6})

    def test_loa_pauses_training_and_unfinished_requirements_carry_past_june(self):
        workbook = r1_book()
        for month in workbook["residents"][0]["postings"][:3]:
            month.update(status="loa", value="LOA")
        original = deepcopy(workbook)
        result = draft_r1_schedule(workbook, STORE)
        self.assertEqual(result["status"], "optimal")
        person = result["residents"][0]
        self.assertTrue(all(m["status"] == "loa" and m["label"] is None for m in person["months"][:3]))
        active = [m for m in person["months"] if m["status"] == "posting"]
        self.assertEqual(len(active), 9)
        self.assertTrue(all(m["target"]["requirement_id"] != "r1.inpatient_psychiatry" for m in active[:6]))
        self.assertTrue(all(m["target"]["requirement_id"] == "r1.inpatient_psychiatry" for m in active[6:]))
        self.assertEqual(person["carryforward"], [{"requirement_id": "r1.inpatient_psychiatry", "institution": active[-1]["target"]["institution"], "months": 3}])
        self.assertEqual(workbook, original)
        for month in workbook["residents"][0]["postings"]:
            month.update(status="loa", value="LOA")
        paused = draft_r1_schedule(workbook, STORE)
        self.assertEqual(paused["status"], "optimal")
        self.assertEqual(paused["soft_targets"]["active_incoming_cohort_size"], 0)
        self.assertEqual(sum(item["months"] for item in paused["residents"][0]["carryforward"]), 12)
        self.assertTrue(all(m["status"] == "loa" for m in paused["residents"][0]["months"]))

    def test_capacity_blank_zero_and_monthly_limits_are_hard_constraints(self):
        workbook = r1_book(3)
        self.assertEqual(draft_r1_schedule(workbook, STORE)["status"], "optimal")
        for row in workbook["postings"]["core"]:
            row["max"] = "2" if row["posting"] == "TTSH General Medicine" else "1" if row["posting"] == "NNI Neurology" else "0" if "Inpatient" not in row["posting"] else None
        result = draft_r1_schedule(workbook, STORE)
        self.assertEqual(result["status"], "optimal")
        for month in range(6):
            counts = Counter(p["months"][month]["label"] for p in result["residents"])
            self.assertEqual(counts, {"TTSH General Medicine": 2, "NNI Neurology": 1})
        for row in workbook["postings"]["core"]:
            if "Inpatient" not in row["posting"]:
                row["max"] = "0"
        impossible = draft_r1_schedule(workbook, STORE)
        self.assertEqual(impossible["status"], "infeasible")
        self.assertEqual(impossible["residents"], [])
        shared = r1_book()
        next(row for row in shared["postings"]["core"] if row["posting"] == "IMH Inpatient Psychiatry")["max"] = "1"
        outside = resident([(m["month"], "IMH Inpatient Psychiatry") for m in shared["months"]], "R4", "Planning", 100)
        shared["residents"].append(outside)
        blocked = draft_r1_schedule(shared, STORE)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(len(blocked["excluded_residents"]), 1)
        self.assertIn({"code": "shared_capacity_outside_r1_scope", "source": outside["postings"][0]["source"]}, blocked["blockers"])

    def test_incoming_targets_24_23_are_soft_and_relax_under_capacity(self):
        for size, targets in ((24, {"TTSH/NNI": 12, "SGH": 9, "NUH": 3}), (23, {"TTSH/NNI": 12, "SGH": 9, "NUH": 2})):
            with self.subTest(size=size):
                result = draft_r1_schedule(r1_book(size), STORE)
                self.assertIn(result["status"], {"optimal", "feasible"})
                self.assertEqual(result["soft_targets"]["routes"], targets)
                self.assertEqual(result["soft_results"]["route_counts"], targets)
                self.assertEqual(result["soft_results"]["distribution_deviation"], 0)
        workbook = r1_book(23)
        next(row for row in workbook["postings"]["core"] if row["posting"] == "NUH Medicine & Neurology")["max"] = "0"
        relaxed = draft_r1_schedule(workbook, STORE)
        self.assertIn(relaxed["status"], {"optimal", "feasible"})
        self.assertEqual(relaxed["soft_results"]["route_counts"]["NUH"], 0)
        self.assertGreater(relaxed["soft_results"]["distribution_deviation"], 0)

    def test_blocked_unknown_and_model_invalid_never_return_fake_solution(self):
        workbook = r1_book()
        unknown = draft_r1_schedule(workbook, STORE, max_seconds=0)
        self.assertEqual(unknown["status"], "unknown")
        self.assertEqual(unknown["residents"], [])
        solve = cp_model.CpSolver.solve

        def invalid_model(solver, model):
            model.new_int_var(1, 0, "invalid_domain")
            return solve(solver, model)

        with patch("r1_solver.cp_model.CpSolver.solve", new=invalid_model):
            invalid = draft_r1_schedule(workbook, STORE)
        self.assertEqual(invalid["status"], "model_invalid")
        self.assertEqual(invalid["residents"], [])
        for change, expected in (("remarks", "unsupported_r1_remarks"), ("history", "unresolved_history"),
                                 ("unsafe_history", "unsafe_historical_identity_evidence_excluded"), ("identity", "unsafe_identity")):
            with self.subTest(change=change):
                changed = deepcopy(workbook)
                if change == "remarks":
                    changed["postings"]["core"][0]["remarks"] = "Compulsory unimplemented restriction"
                elif change == "history":
                    set_history(changed, ["Unknown department"] + ["LOA"] * 11)
                elif change == "unsafe_history":
                    history = set_history(changed, ["SGH General Medicine"] + [None] * 11)
                    changed["issues"] = [{"code": "duplicate_mcr", "records": [{"source": history["source"]}]}]
                else:
                    changed["issues"] = [{"code": "duplicate_mcr", "records": [{"source": changed["residents"][0]["source"]}]}]
                blocked = draft_r1_schedule(changed, STORE)
                self.assertEqual(blocked["status"], "blocked")
                self.assertEqual(blocked["residents"], [])
                self.assertIn(expected, {b["code"] for b in blocked["blockers"]})
                self.assertTrue(all("source" in b or "sources" in b for b in blocked["blockers"]))
        unrelated = deepcopy(workbook)
        unrelated["postings"]["electives"] = [{"residency_year": "R2", "institution": "IMH", "elective": "ANDS",
            "source": {"sheet": "Postings", "row": 100}, "remarks": [{"text": "Unimplemented elective restriction", "source": {"sheet": "Postings", "row": 101}}]}]
        self.assertEqual(draft_r1_schedule(unrelated, STORE)["status"], "optimal")


if __name__ == "__main__":
    unittest.main()
