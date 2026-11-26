from copy import deepcopy
import unittest

from programme_requirements import PROGRAMME_REQUIREMENTS
from tests.catalogue_fixtures import INSTITUTIONS
from scheduler import draft_schedule
from tests.test_r1_solver import STORE
from tests.test_r2_rules import r2_book
from tests.test_requirement_ledger import resident


def r3_book(size=1, complete_r2=True):
    book = r2_book(size)
    for site in INSTITUTIONS["R3"]["Continuity Clinic"]:
        book["postings"]["core"].append({"residency_year": "R3", "posting": f"{site} Continuity Clinic",
            "duration_months": "12", "source": {"sheet": "Postings", "row": 200 + len(book["postings"]["core"])}})
    for person in book["residents"]:
        person["residency_year"] = "R3"
        if complete_r2:
            labels = ["IMH ANDS (Elective)"] * 3 + ["IMH Geriatric Psychiatry"] * 3 + ["IMH Child & Adolescent Psychiatry"] * 3 + ["IMH Addiction Medicine"] * 3
            past = resident([(f"{2026 + (i + 6) // 12}-{(i + 6) % 12 + 1:02d}", label) for i, label in enumerate(labels)], "R2", "R2 history", person["source"]["row"])
            past.update(name=person["name"], mcr=person["mcr"])
            book["annual_sheets"].append({"residents": [past]})
    return book


class R3Tests(unittest.TestCase):
    def test_partial_clinic_resumes_and_loa_pauses(self):
        book = r3_book()
        # Replace the last two R2 months with clinic only after moving R2 history earlier.
        past = book["annual_sheets"][-1]["residents"][0]
        for m in past["postings"]:
            m["month"] = str(int(m["month"][:4]) - 1) + m["month"][4:]
        for m in book["annual_sheets"][0]["residents"][0]["postings"]:
            m["month"] = str(int(m["month"][:4]) - 1) + m["month"][4:]
        book["annual_sheets"].append({"residents": [resident([("2027-05", "TTSH Continuity Clinic"), ("2027-06", "TTSH Continuity Clinic")], "R3", "Clinic")]})
        for index in (1, -1):
            book["residents"][0]["postings"][index].update(status="loa", value="LOA")
        before = deepcopy(book)
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        months = result["residents"][0]["months"]
        self.assertEqual(months[1]["status"], "loa")
        self.assertEqual([m["label"] for m in months if m["status"] == "posting"], ["TTSH Continuity Clinic"] * 10)
        self.assertEqual(book, before)

    def test_earlier_requirements_precede_r3_and_capacity_applies(self):
        book = r3_book(2, complete_r2=False)
        for person in book["residents"]:
            person["residency_year"] = "R2,R3"
            past = resident([(f"2026-{7+i:02d}", label) for i, label in enumerate(
                ["IMH Geriatric Psychiatry"] * 3 + ["IMH Child & Adolescent Psychiatry"] * 3)], "R2", "R2 history", person["source"]["row"])
            past.update(name=person["name"], mcr=person["mcr"])
            book["annual_sheets"].append({"residents": [past]})
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        for person in result["residents"]:
            self.assertTrue(all(m["target"]["requirement_id"].startswith("r2.") for m in person["months"][:6]))
            self.assertTrue(all(m["target"]["requirement_id"] == "r3.continuity_clinic" for m in person["months"][6:]))
            self.assertEqual(sum(c["months"] for c in person["carryforward"]), 6)
        book = r3_book(2)
        for option in book["postings"]["core"]:
            if option["residency_year"] == "R3":
                option["max"] = 1
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        self.assertNotEqual(result["residents"][0]["months"][0]["label"], result["residents"][1]["months"][0]["label"])
        for person in result["residents"]:
            self.assertEqual(len({m["label"] for m in person["months"]}), 1)

    def test_clinic_credit_across_leave_gap_and_other_posting(self):
        from requirement_ledger import build_requirement_ledger
        from tests.rollover_fixtures import following_year
        from tests.test_r5_rules import r5_book

        book = r5_book()
        del book["annual_sheets"][-2:]
        book["residents"][0]["residency_year"] = "R4"
        clinic = "IMH Continuity Clinic"
        book["annual_sheets"].append({"residents": [resident(
            [(f"2025-{m:02d}", clinic) for m in range(7, 11)] + [("2025-11", "LOA"), ("2025-12", "LOA")]
            + [(f"2026-{m:02d}", clinic) for m in range(1, 7)], "R3", "Earlier clinic")]})
        book["annual_sheets"].append({"residents": [resident(
            [("2026-07", "IMH Forensic Psychiatry"), ("2026-08", "IMH Emergency Psychiatry")],
            "R4", "Other rotations")]})
        for remaining, site in ((2, None), (0, clinic), (2, "TTSH Continuity Clinic")):
            with self.subTest(site=site):
                current = deepcopy(book)
                if site:
                    current["annual_sheets"].append({"residents": [resident(
                        [("2027-05", site), ("2027-06", site)], "R3", "Later clinic")]})
                ledger, = build_requirement_ledger(current, STORE)["residents"]
                progress = next(r for r in ledger["requirements"] if r["requirement_year"] == "R3")
                self.assertEqual(progress["remaining_months"], remaining)
                result = draft_schedule(current, STORE, max_seconds=5)
                if site and site != clinic:
                    self.assertEqual(result["status"], "blocked")
                    self.assertIn("conflicting_partial_r3_history", [b["code"] for b in result["blockers"]])
                else:
                    self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
                    months = result["residents"][0]["months"]
                    assigned = [m for m in months if m["target"] and m["target"]["residency_year"] == "R3"]
                    self.assertEqual([m["label"] for m in assigned], [clinic] * remaining)
                    if assigned:
                        following = following_year(current, assigned, "R3")
                        next_ledger, = build_requirement_ledger(following, STORE)["residents"]
                        self.assertEqual(next(r["remaining_months"] for r in next_ledger["requirements"]
                                              if r["requirement_year"] == "R3"), 0)

    def test_completed_clinic_is_not_repeated_for_mixed_r3_r4(self):
        book = r3_book()
        for sheet in book["annual_sheets"]:
            for past in sheet["residents"]:
                if past is book["residents"][0]:
                    continue
                for month in past["postings"]:
                    month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
        from tests.test_r4_rules import add_r4_catalogue
        add_r4_catalogue(book)
        book["residents"][0]["residency_year"] = "R3"  # Completed R3 progresses even before a roster update.
        book["annual_sheets"].append({"residents": [resident(
            [(f"{2026 + (i + 6) // 12}-{(i + 6) % 12 + 1:02d}", "TTSH Continuity Clinic") for i in range(12)],
            "R3", "Clinic")]})
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        self.assertTrue(all(m["target"]["requirement_id"].startswith("r4.") for m in result["residents"][0]["months"]))
        self.assertEqual(result["residents"][0]["carryforward"], [])
        self.assertEqual(result["soft_results"]["r3_missing_clusters"], 0)

    def test_history_and_planning_loa_pause_clinic_and_carry_it_forward(self):
        book = r3_book()
        for sheet in book["annual_sheets"]:
            for past in sheet["residents"]:
                if past is book["residents"][0]:
                    continue
                for month in past["postings"]:
                    month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
        past = resident([(f"2026-{7+i:02d}", "SGH Continuity Clinic") for i in range(6)] +
                        [(f"2027-{i:02d}", "LOA") for i in range(1, 7)], "R3", "Clinic")
        for month in past["postings"][6:]:
            month["status"] = "loa"
        book["annual_sheets"].append({"residents": [past]})
        for month in book["residents"][0]["postings"]:
            month.update(status="loa", value="LOA")
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        person = result["residents"][0]
        self.assertTrue(all(m["status"] == "loa" for m in person["months"]))
        self.assertEqual([(c["institution"], c["months"]) for c in person["carryforward"]], [("SGH", 6)])
        self.assertEqual(result["soft_results"]["r3_missing_clusters"], 0)

    def test_allocation_precedes_r3_cluster_tiebreak(self):
        book = r3_book(6)
        book["postings"]["core"] = [o for o in book["postings"]["core"]
            if o["residency_year"] != "R3" or o["posting"] in {"IMH Continuity Clinic", "NUH Continuity Clinic"}]
        # One resident already has NUHS exposure; the others need it.
        for month in book["annual_sheets"][-1]["residents"][0]["postings"]:
            if month["value"] == "IMH Geriatric Psychiatry":
                month["value"] = "NUH Geriatric Psychiatry"
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "optimal", result["blockers"])
        self.assertEqual(result["soft_priority"], ["capacity_overflow", "incoming_route_distribution", "monthly_medicine_neurology_ratio",
            "posting_balance", "inpatient_allocation", "r3_missing_clusters", "inpatient_destination", "missing_clusters", "singleton_months"])
        nuh = [p for p in result["residents"] if p["months"][0]["label"] == "NUH Continuity Clinic"]
        self.assertEqual(len(nuh), 2)  # Weighted target: four IMH and two NUH.
        self.assertTrue(all("NUHS" not in p["cluster_coverage"]["historical"]["visited"] for p in nuh))
        self.assertEqual(result["soft_results"]["r3_missing_clusters"], 3)

    def test_institution_target_takes_priority_over_avoiding_singletons(self):
        book = r3_book(6)
        book["postings"]["core"] = [o for o in book["postings"]["core"]
            if o["residency_year"] != "R3" or o["posting"] in {
                "IMH Continuity Clinic", "NUH Continuity Clinic", "SGH Continuity Clinic"}]
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "optimal", result["blockers"])
        self.assertEqual(result["soft_results"]["r3_allocation_deviation"], 0)
        # Four IMH and one at each other site beat a singleton-free 2/2/2 split.
        self.assertEqual(result["soft_results"]["singleton_months"], 24)
