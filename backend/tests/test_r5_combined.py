"""R5 combined core is one physical block fulfilling two requirements."""
from collections import Counter
from copy import deepcopy
import unittest

from history_review import ReviewStore
from requirement_ledger import build_requirement_ledger
from scheduler import draft_schedule
from tests.test_r5_rules import r5_book
from tests.test_requirement_ledger import resident

STORE = ReviewStore(version=1, decisions=[])
COMBINED = "r5.child_geriatric_psychiatry"
CHILD = "r5.child_adolescent_psychiatry"
GERI = "r5.geriatric_psychiatry"
LABEL = "NUH Child and Geriatric Psychiatry"


def combined_book():
    book = r5_book()
    book["postings"]["core"].append({"residency_year": "R5", "posting": LABEL,
        "duration_months": "6", "max": "1", "source": {"sheet": "Postings", "row": 900}})
    return book


def add_history(book, months):
    for sheet in book["annual_sheets"]:
        for past in sheet["residents"]:
            if past is not book["residents"][0]:
                for month in past["postings"]:
                    month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
    book["annual_sheets"].append({"residents": [resident(months, "R5", "R5 history")]})


class R5CombinedTests(unittest.TestCase):
    def test_request_selects_combined_route_once_with_capacity_fallback(self):
        book = combined_book()
        book["requests"] = [{"matched_resident_source": book["residents"][0]["source"],
            "posting_request": LABEL, "period": "Jul - Dec 2027", "source": {"sheet": "Request", "row": 2}}]
        before = deepcopy(book)
        result = draft_schedule(book, STORE, max_seconds=10)
        self.assertIn(result["status"], {"optimal", "feasible"}, result)
        self.assertEqual(result["residents"][0]["requests"][0]["status"], "met")
        months = result["residents"][0]["months"]
        counts = Counter(m["target"]["requirement_id"] for m in months if m["target"])
        self.assertEqual(counts, {COMBINED: 6, "r5.elective": 6})
        self.assertEqual([m["label"] for m in months[:6]], [LABEL] * 6)
        self.assertEqual(sum(m["target"] is None for m in months), 0)
        self.assertEqual(book, before)
        # A preferred combined posting cannot override its capacity.
        book["postings"]["core"][-1]["max"] = "0"
        result = draft_schedule(book, STORE, max_seconds=10)
        self.assertIn(result["status"], {"optimal", "feasible"}, result)
        counts = Counter(m["target"]["requirement_id"] for m in result["residents"][0]["months"])
        self.assertEqual(counts, {CHILD: 3, GERI: 3, "r5.elective": 6})
        outcome = result["residents"][0]["requests"][0]
        self.assertEqual(outcome["status"], "not_met")
        self.assertEqual(len(outcome["assigned"]), 2)

    def test_completed_combined_history_credits_both_without_repeating_cores(self):
        book = combined_book()
        add_history(book, [(f"2027-{m:02d}", LABEL) for m in range(1, 7)])
        ledger = build_requirement_ledger(book, STORE)["residents"][0]
        by_id = {r["requirement_id"]: r for r in ledger["requirements"]}
        for key in (CHILD, GERI, COMBINED):
            self.assertEqual(by_id[key]["expected_months"], 6 if key == COMBINED else 3)
            self.assertEqual(by_id[key]["remaining_months"], 0)
        self.assertEqual(sum(m.get("requirement_id") == COMBINED for m in ledger["months"]), 6)
        result = draft_schedule(book, STORE, max_seconds=10)
        self.assertIn(result["status"], {"optimal", "feasible"}, result)
        self.assertEqual(Counter(m["target"]["requirement_id"] for m in result["residents"][0]["months"] if m["target"]),
                         {"r5.elective": 6})

        # The same label explicitly marked Elective does not grant core credit.
        book["postings"]["electives"].append({"residency_year": "R5", "institution": "NUH",
            "elective": "Child and Geriatric Psychiatry", "remarks": [], "source": {"sheet": "Postings", "row": 902}})
        for month in book["annual_sheets"][-1]["residents"][0]["postings"]:
            month["value"] += " (Elective)"
        by_id = {r["requirement_id"]: r for r in build_requirement_ledger(book, STORE)["residents"][0]["requirements"]}
        self.assertEqual(by_id["r5.elective"]["expected_months"], 6)
        self.assertEqual(by_id[CHILD]["expected_months"], 0)
        self.assertEqual(by_id[GERI]["expected_months"], 0)

    def test_partial_combined_resumes_same_site_and_loa_pauses_it(self):
        book = combined_book()
        add_history(book, [("2027-06", LABEL)])
        by_id = {r["requirement_id"]: r for r in build_requirement_ledger(book, STORE)["residents"][0]["requirements"]}
        self.assertEqual(by_id[COMBINED]["remaining_months"], 5)
        self.assertEqual(by_id[CHILD]["expected_months"], 0)
        self.assertEqual(by_id[GERI]["expected_months"], 0)
        book["postings"]["core"].append({**book["postings"]["core"][-1],
            "posting": "IMH Child and Geriatric Psychiatry", "source": {"sheet": "Postings", "row": 901}})
        book["residents"][0]["postings"][0].update(status="loa", value="LOA")
        result = draft_schedule(book, STORE, max_seconds=10)
        self.assertIn(result["status"], {"optimal", "feasible"}, result)
        months = result["residents"][0]["months"]
        self.assertIsNone(months[0]["target"])
        self.assertEqual([m["label"] for m in months[1:6]], [LABEL] * 5)
        self.assertEqual(Counter(m["target"]["requirement_id"] for m in months if m["target"]),
                         {COMBINED: 5, "r5.elective": 6})

    def test_partial_separate_core_continues_separate_route(self):
        book = combined_book()
        add_history(book, [("2027-06", "IMH Geriatric Psychiatry")])
        result = draft_schedule(book, STORE, max_seconds=10)
        self.assertIn(result["status"], {"optimal", "feasible"}, result)
        months = result["residents"][0]["months"]
        self.assertEqual([m["label"] for m in months[:2]], ["IMH Geriatric Psychiatry"] * 2)
        self.assertNotIn(COMBINED, [m["target"]["requirement_id"] for m in months if m["target"]])


if __name__ == "__main__":
    unittest.main()
