from collections import Counter
from copy import deepcopy
import unittest

from scheduler import draft_schedule
from scheduler_inputs import prepare_scheduler_inputs
from tests.test_r1_solver import STORE
from tests.test_r4_rules import r4_book
from tests.test_requirement_ledger import resident


def r5_book():
    book = r4_book()
    for sheet in book["annual_sheets"]:
        for past in sheet["residents"]:
            if past is book["residents"][0]:
                continue
            for month in past["postings"]:
                month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
    labels = ["NUH Inpatient Psychiatry"] * 3 + ["SGH Consultation Liaison Psychiatry"] * 3 + ["IMH Emergency Psychiatry"] * 3 + ["IMH Forensic Psychiatry"] * 3
    book["annual_sheets"].append({"residents": [resident(
        [(f"{2026 + (i + 6) // 12}-{(i + 6) % 12 + 1:02d}", label) for i, label in enumerate(labels)], "R4", "R4 history")]})
    for name, sites in (("Geriatric Psychiatry", ("IMH", "CGH", "NUH")),
                        ("Child & Adolescent Psychiatry", ("IMH", "NUH", "KKH"))):
        for site in sites:
            book["postings"]["core"].append({"residency_year": "R5", "posting": f"{site} {name}",
                "duration_months": "3", "source": {"sheet": "Postings", "row": 600 + len(book["postings"]["core"])}})
    book["postings"]["electives"].append({"residency_year": "R5", "institution": "IMH", "elective": "Forensic Psychiatry", "remarks": [],
        "source": {"sheet": "Postings", "row": 500}})
    book["residents"][0]["residency_year"] = "R5"
    return book


class R5Tests(unittest.TestCase):
    def test_full_r5_with_workbook_catalogue(self):
        book = r5_book()
        before = deepcopy(book)
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        person = result["residents"][0]
        self.assertEqual(Counter(m["target"]["requirement_id"] for m in person["months"]),
                         {"r5.geriatric_psychiatry": 3, "r5.child_adolescent_psychiatry": 3, "r5.elective": 6})
        self.assertTrue(all(m["target"]["source"]["sheet"] == "Postings" for m in person["months"]))
        for requirement in {m["target"]["requirement_id"] for m in person["months"]}:
            indices = [i for i, m in enumerate(person["months"]) if m["target"]["requirement_id"] == requirement]
            self.assertEqual(indices, list(range(indices[0], indices[-1] + 1)))
            self.assertEqual(len({person["months"][i]["label"] for i in indices}), 1)
        self.assertEqual(book, before)

    def test_added_geriatric_sites_count_history_and_schedule_remaining_months(self):
        for site in ("TTSH", "SKH"):
            with self.subTest(site=site):
                book = r5_book()
                for sheet in book["annual_sheets"]:
                    for past in sheet["residents"]:
                        if past is not book["residents"][0]:
                            for month in past["postings"]:
                                month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
                label = f"{site} Geriatric Psychiatry"
                book["postings"]["core"].append({"residency_year": "R5", "posting": label,
                    "duration_months": "3", "max": "1", "source": {"sheet": "Postings", "row": 700}})
                book["annual_sheets"].append({"residents": [resident(
                    [("2027-06", label)], "R5", "R5 history")]})
                result = draft_schedule(book, STORE)
                self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
                self.assertEqual([m["label"] for m in result["residents"][0]["months"][:2]], [label] * 2)
                book["postings"]["core"].pop()
                prepared = prepare_scheduler_inputs(book, STORE)
                requirement = next(r for r in prepared["residents"][0]["requirements"]
                                   if r["requirement_id"] == "r5.geriatric_psychiatry")
                self.assertEqual(requirement["expected_months"], 0)
                self.assertFalse(prepared["residents"][0]["input_ready"])

    def test_explicit_core_capacity_and_history_credit(self):
        book = r5_book()
        book["postings"]["core"] = [o for o in book["postings"]["core"] if o["residency_year"] != "R5"
                                    or "Geriatric Psychiatry" not in o["posting"] or o["posting"] == "NUH Geriatric Psychiatry"]
        next(o for o in book["postings"]["core"] if o["residency_year"] == "R5" and o["posting"] == "NUH Geriatric Psychiatry")["max"] = "1"
        options = prepare_scheduler_inputs(book, STORE)["catalogue_options"]
        geri = [o for o in options if o["requirement_id"] == "r5.geriatric_psychiatry"]
        self.assertEqual([(o["institution"], o["capacity"]) for o in geri], [("NUH", 1)])
        # Recognised R5 core history uses the explicit workbook catalogue.
        for sheet in book["annual_sheets"]:
            for past in sheet["residents"]:
                if past is book["residents"][0]:
                    continue
                for month in past["postings"]:
                    month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
        book["annual_sheets"].append({"residents": [resident([("2027-06", "NUH Geriatric Psychiatry")], "R5", "R5 history")]})
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        self.assertEqual([m["label"] for m in result["residents"][0]["months"][:2]], ["NUH Geriatric Psychiatry"] * 2)
        next(o for o in book["postings"]["core"] if o["residency_year"] == "R5" and o["posting"] == "NUH Geriatric Psychiatry")["max"] = "0"
        self.assertEqual(draft_schedule(book, STORE)["status"], "infeasible")

    def test_mixed_r4_r5_and_loa_carryforward(self):
        book = r5_book()
        for month in book["annual_sheets"][-1]["residents"][0]["postings"][-3:]:
            month.update(status="loa", value="LOA")
        book["residents"][0]["residency_year"] = "R4,R5"
        book["residents"][0]["postings"][1].update(status="loa", value="LOA")
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        person = result["residents"][0]
        self.assertEqual([person["months"][i]["target"]["requirement_id"] for i in (0, 2, 3)], ["r4.forensic_psychiatry"] * 3)
        self.assertEqual(sum(item["months"] for item in person["carryforward"]), 4)

    def test_unfinished_r2_precedes_r5_even_after_later_history(self):
        book = r5_book()
        r2 = next(p for sheet in book["annual_sheets"] for p in sheet["residents"]
                  if p.get("residency_year") == "R2")
        for month in r2["postings"][:3]:
            month.update(status="loa", value="LOA")
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        months = result["residents"][0]["months"]
        self.assertTrue(all(m["target"]["requirement_id"] == "r2.elective" for m in months[:3]))
        self.assertTrue(all(m["target"]["requirement_id"].startswith("r5.") for m in months[3:]))
        self.assertEqual(sum(item["months"] for item in result["residents"][0]["carryforward"]), 3)

    def test_duration_aware_balance_and_weighted_sites(self):
        book = r5_book()
        for sheet in book["annual_sheets"]:
            for original in list(sheet["residents"]):
                for i in range(1, 4):
                    duplicate = deepcopy(original)
                    duplicate.update(name=f"R5 Resident {i}", mcr=f"R5-{i}", source={**original["source"], "row": i + 3})
                    for month in duplicate["postings"]:
                        month["source"]["row"] = i + 3
                    sheet["residents"].append(duplicate)
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "optimal", result["blockers"])
        people = result["residents"]
        for month in range(12):
            counts = Counter(p["months"][month]["target"]["requirement_id"] for p in people)
            self.assertEqual(counts, {"r5.geriatric_psychiatry": 1, "r5.child_adolescent_psychiatry": 1, "r5.elective": 2})
        geri = Counter(next(m["target"]["institution"] for m in p["months"]
                            if m["target"]["requirement_id"] == "r5.geriatric_psychiatry") for p in people)
        self.assertEqual(geri, {"IMH": 2, "CGH": 1, "NUH": 1})
        self.assertEqual(result["soft_results"]["r5_allocation_deviation"], 0)
        # Once the elective is completed, only the remaining two cores balance.
        for sheet in book["annual_sheets"]:
            for past in sheet["residents"]:
                if any(past is person for person in book["residents"]):
                    continue
                for month in past["postings"]:
                    month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
        histories = []
        for i, person in enumerate(book["residents"]):
            past = resident([(f"2027-{m:02d}", "IMH Forensic Psychiatry (Elective)") for m in range(1, 7)], "R5", "R5 elective", i + 3)
            past.update(name=person["name"], mcr=person["mcr"])
            histories.append(past)
        book["annual_sheets"].append({"residents": histories})
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "optimal", result["blockers"])
        for month in range(6):
            counts = Counter(p["months"][month]["target"]["requirement_id"] for p in result["residents"])
            self.assertEqual(counts, {"r5.geriatric_psychiatry": 2, "r5.child_adolescent_psychiatry": 2})

    def test_r5_cannot_satisfy_r4_cluster_deadline(self):
        book = r5_book()
        history = book["annual_sheets"][-1]["residents"][0]["postings"]
        for month in history:
            if month["value"] in {"NUH Inpatient Psychiatry", "SGH Consultation Liaison Psychiatry"}:
                month["value"] = "TTSH " + month["value"].split(" ", 1)[1]
        for month in history[-3:]:
            month.update(status="loa", value="LOA")
        book["residents"][0]["residency_year"] = "R4,R5"
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "infeasible")

    def test_unsupported_electives_are_excluded_without_blocking_standard_choices(self):
        book = r5_book()
        book["postings"]["electives"].append({"residency_year": "R5", "institution": "SGH", "elective": "Psychogeriatrics Psychiatry",
            "remarks": [{"text": "(which will meet the core 3months R5 Psychogeriatrics requirements)"}], "source": {"sheet": "Postings", "row": 501}})
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        self.assertFalse(any(m["label"] == "SGH Psychogeriatrics Psychiatry" for m in result["residents"][0]["months"]))
        self.assertTrue(any("overlap" in item for item in result["limitations"]))
        # A partial unsupported elective cannot be switched to the standard one.
        for sheet in book["annual_sheets"]:
            for past in sheet["residents"]:
                if past is book["residents"][0]:
                    continue
                for month in past["postings"]:
                    month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
        book["annual_sheets"].append({"residents": [resident([("2027-06", "SGH Psychogeriatrics Psychiatry (Elective)")], "R5", "Partial")]})
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("missing_r5_catalogue_option", [r["code"] for r in result["skipped_residents"][0]["reasons"]])

    def test_absent_core_catalogue_is_reported_not_synthesised(self):
        book = r5_book()
        book["postings"]["core"] = [o for o in book["postings"]["core"] if o["residency_year"] != "R5"]
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("missing_r5_catalogue_option", [r["code"] for r in result["skipped_residents"][0]["reasons"]])


if __name__ == "__main__":
    unittest.main()
