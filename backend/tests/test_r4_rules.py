from collections import Counter
from copy import deepcopy
import unittest

from programme_requirements import PROGRAMME_REQUIREMENTS
from scheduler import draft_schedule
from tests.test_r1_solver import STORE
from tests.test_r3_rules import r3_book
from tests.test_r2_rules import r2_book
from tests.test_requirement_ledger import resident


def add_r4_catalogue(book):
    for name, rule in PROGRAMME_REQUIREMENTS["R4"].items():
        for site in rule["institutions"]:
            book["postings"]["core"].append({"residency_year": "R4", "posting": f"{site} {name}",
                "duration_months": "3", "source": {"sheet": "Postings", "row": 300 + len(book["postings"]["core"])}})


def r4_book():
    book = r3_book()
    add_r4_catalogue(book)
    for sheet in book["annual_sheets"]:
        for past in sheet["residents"]:
            if past is book["residents"][0]:
                continue
            for month in past["postings"]:
                month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
    book["annual_sheets"].append({"residents": [resident(
        [(f"{2026 + (i + 6) // 12}-{(i + 6) % 12 + 1:02d}", "TTSH Continuity Clinic") for i in range(12)],
        "R3", "Clinic")]})
    book["residents"][0]["residency_year"] = "R4,R5"
    return book


class R4Tests(unittest.TestCase):
    def test_full_year_blocks_cluster_completion_and_r1_imh_exclusion(self):
        result = draft_schedule(r4_book(), STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        person = result["residents"][0]
        months = person["months"]
        self.assertEqual(Counter(m["target"]["requirement_id"] for m in months),
                         {rule["id"]: 3 for rule in PROGRAMME_REQUIREMENTS["R4"].values()})
        for start in range(0, 12, 3):
            self.assertEqual(len({m["label"] for m in months[start:start + 3]}), 1)
        self.assertFalse(any(m["label"] == "IMH Inpatient Psychiatry" for m in months))
        self.assertEqual(person["cluster_coverage"]["projected"]["missing"], [])
        self.assertEqual(person["carryforward"], [])

    def test_partial_resumes_same_site_and_loa_pauses(self):
        book = r4_book()
        for sheet in book["annual_sheets"]:
            for past in sheet["residents"]:
                if past is book["residents"][0]:
                    continue
                for month in past["postings"]:
                    month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
        book["annual_sheets"].append({"residents": [resident([("2027-06", "NUH Consultation Liaison Psychiatry")], "R4", "Partial")]})
        book["residents"][0]["postings"][1].update(status="loa", value="LOA")
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        months = result["residents"][0]["months"]
        self.assertEqual([months[i]["label"] for i in (0, 2)], ["NUH Consultation Liaison Psychiatry"] * 2)
        self.assertEqual(months[1]["status"], "loa")

    def test_r3_progression_and_loa_carry_r4_forward(self):
        book = r4_book()
        book["residents"][0]["residency_year"] = "R3,R4"
        for month in book["annual_sheets"][-1]["residents"][0]["postings"][-2:]:
            month.update(status="loa", value="LOA")
        book["residents"][0]["postings"][1].update(status="loa", value="LOA")
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        person = result["residents"][0]
        self.assertEqual([person["months"][i]["target"]["requirement_id"] for i in (0, 2)], ["r3.continuity_clinic"] * 2)
        self.assertEqual(sum(item["months"] for item in person["carryforward"]), 3)

    def test_future_options_do_not_grant_projected_cluster_credit(self):
        book = r4_book()
        # NUHS is available only in the unfinished R3 block, beyond the horizon.
        book["annual_sheets"].pop()
        book["postings"]["core"] = [o for o in book["postings"]["core"]
            if o["residency_year"] != "R3" or o["posting"] == "NUH Continuity Clinic"]
        book["postings"]["core"] = [o for o in book["postings"]["core"]
            if o["residency_year"] != "R4" or o["posting"].split()[0] in {"IMH", "TTSH", "KTPH"}]
        for month in book["residents"][0]["postings"]:
            month.update(status="loa", value="LOA")
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        person = result["residents"][0]
        self.assertIn("NUHS", person["cluster_coverage"]["projected"]["missing"])
        self.assertEqual(sum(item["months"] for item in person["carryforward"]), 24)
        self.assertTrue(any(item["requirement_id"] == "r3.continuity_clinic" and item["institution"] == "NUH"
                            for item in person["carryforward"]))

    def test_disconnected_partial_r4_is_flagged(self):
        book = r4_book()
        for sheet in book["annual_sheets"]:
            for past in sheet["residents"]:
                if past is book["residents"][0]:
                    continue
                for month in past["postings"]:
                    month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
        # A second resident shares the valid prerequisite history but not the
        # conflicting partial posting; the first must not block their draft.
        for sheet in book["annual_sheets"]:
            for original in list(sheet["residents"]):
                duplicate = deepcopy(original)
                duplicate.update(name="Second Resident", mcr="SECOND", source={**original["source"], "row": 4})
                for month in duplicate["postings"]:
                    month["source"]["row"] = 4
                sheet["residents"].append(duplicate)
        book["annual_sheets"].append({"residents": [resident(
            [("2027-04", "NUH Consultation Liaison Psychiatry"), ("2027-06", "NUH Consultation Liaison Psychiatry")], "R4", "Partial")]})
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        self.assertEqual([person["name"] for person in result["residents"]], ["Second Resident"])
        self.assertIn("conflicting_partial_r4_history", [reason["code"] for reason in result["skipped_residents"][0]["reasons"]])

    def test_weighted_inpatient_and_even_cl_targets_with_cluster_priority(self):
        book = r4_book()
        for sheet in book["annual_sheets"]:
            for past in sheet["residents"]:
                if past is book["residents"][0]:
                    continue
                for month in past["postings"]:
                    if month["value"] == "IMH Inpatient Psychiatry":
                        month["value"] = "SGH Inpatient Psychiatry"
                    if month["value"] == "TTSH Continuity Clinic":
                        month["value"] = "NUH Continuity Clinic"
        allowed = {"IMH Inpatient Psychiatry", "SGH Inpatient Psychiatry",
                   "TTSH Consultation Liaison Psychiatry", "NUH Consultation Liaison Psychiatry"}
        book["postings"]["core"] = [o for o in book["postings"]["core"]
            if o["residency_year"] != "R4" or "Inpatient Psychiatry" not in o["posting"]
            and "Consultation Liaison Psychiatry" not in o["posting"] or o["posting"] in allowed]
        for sheet in book["annual_sheets"]:
            for original in list(sheet["residents"]):
                for i in range(1, 6):
                    duplicate = deepcopy(original)
                    duplicate.update(name=f"Resident {i}", mcr=f"NEW{i}", source={**original["source"], "row": i + 3})
                    for month in duplicate["postings"]:
                        month["source"]["row"] = i + 3
                    sheet["residents"].append(duplicate)
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "optimal", result["blockers"])
        people = result["residents"]
        ip = Counter(next(m["label"] for m in p["months"] if m["target"]["requirement_id"] == "r4.inpatient_psychiatry") for p in people)
        cl = Counter(next(m["label"] for m in p["months"] if m["target"]["requirement_id"] == "r4.consultation_liaison_psychiatry") for p in people)
        self.assertEqual(ip, {"IMH Inpatient Psychiatry": 4, "SGH Inpatient Psychiatry": 2})
        self.assertEqual(cl, {"TTSH Consultation Liaison Psychiatry": 3, "NUH Consultation Liaison Psychiatry": 3})
        self.assertEqual(result["soft_results"]["r4_allocation_deviation"], 0)
        # Without previous NUHS exposure, all six need NUH despite the CL target.
        for past in book["annual_sheets"][-1]["residents"]:
            for month in past["postings"]:
                month["value"] = "TTSH Continuity Clinic"
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        self.assertTrue(all(any(m["label"] == "NUH Consultation Liaison Psychiatry" for m in p["months"]) for p in result["residents"]))
        self.assertTrue(all(not p["cluster_coverage"]["projected"]["missing"] for p in result["residents"]))

    def test_r2_and_r4_are_balanced_independently_each_month(self):
        book = r4_book()
        # Different cohort sizes expose accidental pooling of the two years.
        for sheet in book["annual_sheets"]:
            for original in list(sheet["residents"]):
                for i in range(1, 4):
                    duplicate = deepcopy(original)
                    duplicate.update(name=f"R4 Resident {i}", mcr=f"R4-{i}", source={**original["source"], "row": i + 3})
                    for month in duplicate["postings"]:
                        month["source"]["row"] = i + 3
                    sheet["residents"].append(duplicate)
        r2 = r2_book(2)
        for person in r2["residents"]:
            person["name"] = "R2 " + person["name"]
            person["mcr"] = "R2-" + person["mcr"]
            person["source"]["sheet"] = "R2 Planning"
            for month in person["postings"]:
                month["source"]["sheet"] = "R2 Planning"
        for sheet in r2["annual_sheets"]:
            if any(person is r2["residents"][0] for person in sheet["residents"]):
                continue
            for person in sheet["residents"]:
                person["name"] = "R2 " + person["name"]
                person["mcr"] = "R2-" + person["mcr"]
                person["source"]["sheet"] = "R2 History"
                for month in person["postings"]:
                    month["source"]["sheet"] = "R2 History"
            book["annual_sheets"].append(sheet)
        book["residents"].extend(r2["residents"])
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "optimal", result["blockers"])
        for month in range(12):
            for year, size in (("r2.", 2), ("r4.", 4)):
                counts = Counter(p["months"][month]["target"]["requirement_id"] for p in result["residents"]
                                 if p["months"][month]["target"]["requirement_id"].startswith(year))
                self.assertEqual(len(counts), size)
                self.assertEqual(set(counts.values()), {1})
        self.assertEqual(result["soft_results"]["posting_balance"], 48)

    def test_missing_cluster_cannot_be_credited_by_impossible_site(self):
        book = r4_book()
        for option in book["postings"]["core"]:
            if option["residency_year"] == "R4" and option["posting"].split()[0] in {"NUH", "NTFGH"}:
                option["max"] = 0
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "infeasible")
        self.assertIn("r4_schedule_infeasible", [b["code"] for b in result["blockers"]])


if __name__ == "__main__":
    unittest.main()
