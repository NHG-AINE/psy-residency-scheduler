from copy import deepcopy
import json
import unittest

from fastapi.testclient import TestClient
from draft_edits import validate_draft_change
from main import app
from scheduler import draft_schedule
from tests.test_r1_solver import STORE, r1_book
from tests.test_r2_rules import r2_book
from tests.test_r3_rules import r3_book
from tests.test_r4_rules import r4_book
from tests.test_r5_combined import combined_book, LABEL


class DraftEditTests(unittest.TestCase):
    def edit(self, book, draft, start, option):
        return validate_draft_change(book, STORE, draft, {
            "kind": "edit", "resident": draft["residents"][0]["source"], "start": start,
            "posting": option["posting"], "institution": option["institution"], "offering": option["source"]})

    def test_capacity_edit_keeps_other_residents_fixed_and_clears_resolved_warnings(self):
        book = r2_book(2)
        for row in book["postings"]["core"]:
            if row["posting"].startswith("NUH Child"):
                row["max"] = "0"
        draft = draft_schedule(book, STORE)
        person, other = draft["residents"]
        original = deepcopy(draft)
        month = next(m for m in person["months"] if m["target"]["requirement_id"] == "r2.child_adolescent_psychiatry")
        target = next(o for o in draft["edit_options"] if o["label"].startswith("NUH Child"))
        change = self.edit(book, draft, month["block_start"], target)
        edited = change["draft"]
        self.assertEqual(edited["status"], "edited")
        self.assertEqual(other["months"], edited["residents"][1]["months"])
        warnings = [issue for issue in change["issues"] if issue["code"] == "capacity_overflow"]
        self.assertTrue(warnings)
        self.assertIn("1 resident in Child", warnings[0]["message"])
        self.assertIn("The max is 0.", warnings[0]["message"])
        other_starts = list(dict.fromkeys(m["block_start"] for m in person["months"] if m["block_start"] != month["block_start"]))
        swapped = validate_draft_change(book, STORE, edited, {"kind": "swap", "resident": person["source"],
            "start": other_starts[0], "destination": other_starts[1]})["draft"]
        self.assertTrue(any(i["code"] == "capacity_overflow" for i in swapped["edit_warnings"]))
        restore = next(o for o in draft["edit_options"] if o["source"] == month["target"]["source"])
        corrected = self.edit(book, swapped, month["block_start"], restore)["draft"]
        self.assertFalse(any(i["code"] == "capacity_overflow" for i in corrected["edit_warnings"]))
        self.assertEqual(draft, original)

    def test_leave_pauses_a_whole_block_and_cannot_be_a_swap_destination(self):
        book = r3_book()
        book["residents"][0]["postings"][3].update(status="loa", value="LOA")
        draft = draft_schedule(book, STORE)
        person, = draft["residents"]
        first, leave = person["months"][0], person["months"][3]
        self.assertEqual({m["block_start"] for m in person["months"] if m["target"]}, {first["month"]})
        target = next(o for o in draft["edit_options"] if o["residency_year"] == "R3" and o["label"] != first["label"])
        updated = self.edit(book, draft, first["month"], target)["draft"]["residents"][0]
        self.assertEqual(updated["months"][3], leave)
        self.assertEqual({m["label"] for m in updated["months"] if m["target"]}, {target["label"]})
        self.assertEqual(updated["carryforward"][0]["institution"], target["institution"])
        response = validate_draft_change(book, STORE, draft, {"kind": "swap", "resident": person["source"],
            "start": first["month"], "destination": leave["month"]})
        self.assertIsNone(response["draft"])
        self.assertIn("recorded as leave", response["issues"][0]["message"])

    def test_r4_history_excludes_imh_for_inpatient_and_rejects_stale_offering(self):
        book = r4_book()
        draft = draft_schedule(book, STORE)
        person, = draft["residents"]
        first = next(m for m in person["months"] if m["target"]["requirement_id"] == "r4.inpatient_psychiatry")
        imh = next(o for o in draft["edit_options"] if o["residency_year"] == "R4" and o["label"] == "IMH Inpatient Psychiatry")
        blocked = self.edit(book, draft, first["block_start"], imh)
        self.assertIsNone(blocked["draft"])
        self.assertIn("R1 Inpatient Psychiatry", blocked["issues"][0]["message"])
        changed = {**imh, "source": {"sheet": "Postings", "row": 9999}}
        self.assertEqual(self.edit(book, draft, first["block_start"], changed)["issues"][0]["code"], "catalogue_offering")

    def test_mixed_year_options_still_require_r2_before_r3(self):
        book = r3_book(complete_r2=False)
        book["residents"][0]["residency_year"] = "R2;R3"
        draft = draft_schedule(book, STORE, max_seconds=5)
        person, = draft["residents"]
        clinic = next(o for o in draft["edit_options"] if o["residency_year"] == "R3")
        rejected = self.edit(book, draft, person["months"][0]["block_start"], clinic)
        self.assertIsNone(rejected["draft"])
        self.assertIn("Complete R2 before starting R3", rejected["issues"][0]["message"])

    def test_r1_cannot_mix_a_paired_medicine_and_neurology_route(self):
        book = r1_book()
        draft = draft_schedule(book, STORE, max_seconds=5)
        person, = draft["residents"]
        neurology = next(m for m in person["months"] if m["target"]["requirement_id"] == "r1.neurology")
        wrong_site = next(o for o in draft["edit_options"] if o["requirement_id"] == "r1.neurology" and o["label"] != neurology["label"])
        rejected = self.edit(book, draft, neurology["block_start"], wrong_site)
        self.assertIsNone(rejected["draft"])
        self.assertIn("NNI Neurology", rejected["issues"][0]["message"])

    def test_swap_r5_shared_credit_and_recalculate_the_request_through_api(self):
        book = combined_book()
        source = book["residents"][0]["source"]
        book["requests"] = [{"matched_resident_source": source, "posting_request": LABEL,
                             "period": "Jul - Dec 2027", "source": {"sheet": "Request", "row": 2}}]
        draft = draft_schedule(book, STORE)
        person, = draft["residents"]
        self.assertEqual(person["requests"][0]["status"], "met")
        starts = list(dict.fromkeys(m["block_start"] for m in person["months"]))
        self.assertEqual(len(starts), 2)
        response = TestClient(app).post("/api/draft/validate-change", json={
            "workbook": book, "store": STORE.model_dump(), "draft": draft,
            "change": {"kind": "swap", "resident": source, "start": starts[0], "destination": starts[1]}})
        self.assertEqual(response.status_code, 200, response.text)
        changed = response.json()
        updated = changed["draft"]["residents"][0]
        self.assertEqual(updated["months"][6]["label"], LABEL)
        self.assertEqual(updated["carryforward"], [])
        self.assertEqual(updated["requests"][0]["status"], "not_met")
        self.assertTrue(any(i["code"] == "resident_requests" for i in changed["issues"]))
