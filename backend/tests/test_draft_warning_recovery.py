from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch

from draft_edits import DraftWarningBaselineRequired, validate_draft_change
from scheduler import draft_schedule
from tests.test_r1_solver import STORE
from tests.test_r2_rules import r2_book


class DraftWarningRecoveryTests(TestCase):
    def setUp(self):
        self.book = r2_book(2)
        for row in self.book["postings"]["core"]:
            if row["posting"].startswith("NUH Child"):
                row["max"] = "0"
        self.draft = draft_schedule(self.book, STORE, max_seconds=5)
        person = self.draft["residents"][0]
        self.block = next(month for month in person["months"]
                          if month["target"]["requirement_id"] == "r2.child_adolescent_psychiatry")
        self.option = next(option for option in self.draft["edit_options"] if option["label"].startswith("NUH Child"))

    def change(self, option):
        return {"kind": "edit", "resident": self.draft["residents"][0]["source"], "start": self.block["block_start"],
                "posting": option["posting"], "institution": option["institution"], "offering": option["source"]}

    def test_legacy_current_diagnostics_match_a_modern_edit(self):
        change = self.change(self.option)
        with patch("draft_edits.draft_schedule", wraps=draft_schedule) as schedule:
            expected = validate_draft_change(self.book, STORE, self.draft, change)
        self.assertEqual(schedule.call_count, 1)
        self.assertIn("inpatient_allocation", {issue["code"] for issue in expected["issues"]})
        self.assertIn("capacity_overflow", {issue["code"] for issue in expected["issues"]})
        for missing in ("soft_results.site_allocations", "soft_results.route_counts", "soft_results.monthly_ratios",
                        "capacity_overflows", "singletons", "preference_scores", "preference_scores.posting_balance"):
            with self.subTest(missing=missing):
                saved = deepcopy(self.draft)
                parent, _, field = missing.rpartition(".")
                del (saved[parent] if parent else saved)[field]
                before = deepcopy(saved)
                result = validate_draft_change(self.book, STORE, saved, change)
                self.assertEqual(result["issues"], expected["issues"])
                self.assertEqual(result["draft"]["edit_baseline"], expected["draft"]["edit_baseline"])
                self.assertEqual(result["draft"]["residents"], expected["draft"]["residents"])
                self.assertEqual(saved, before)

    def test_older_edited_draft_recovers_its_original_baseline_when_reversed(self):
        edited = validate_draft_change(self.book, STORE, self.draft, self.change(self.option))["draft"]
        saved = deepcopy(edited)
        del saved["edit_baseline"]["preference_scores"]["posting_balance"]
        del saved["edit_baseline"]["soft_results"]["route_counts"]["NUH"]
        saved["edit_baseline"]["soft_results"]["monthly_ratios"].pop()
        original = next(option for option in self.draft["edit_options"] if option["source"] == self.block["target"]["source"])
        change = self.change(original)
        with self.assertRaises(DraftWarningBaselineRequired):
            validate_draft_change(self.book, STORE, saved, change)
        with self.assertRaisesRegex(ValueError, "do not match"):
            validate_draft_change(self.book, STORE, saved, change, edited["residents"])
        result = validate_draft_change(self.book, STORE, saved, change, self.draft["residents"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["draft"]["edit_warnings"], [])
        self.assertEqual(result["draft"]["edit_baseline"], edited["edit_baseline"])
        self.assertEqual([p["months"] for p in result["draft"]["residents"]], [p["months"] for p in self.draft["residents"]])

    def test_missing_offering_identifies_the_saved_resident_and_month(self):
        saved = deepcopy(self.draft)
        del saved["soft_results"]["site_allocations"]
        resident = saved["residents"][0]
        for month in resident["months"][:2]:
            month["target"]["source"] = {"sheet": "Postings", "row": 9999}
        with self.assertRaisesRegex(ValueError, f"{resident['name']} in July"):
            validate_draft_change(self.book, STORE, saved, self.change(self.option))
