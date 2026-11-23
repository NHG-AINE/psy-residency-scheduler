import unittest

from draft_edits import validate_draft_change
from scheduler import draft_schedule
from tests.test_r1_solver import STORE
from tests.test_r5_combined import CHILD, GERI
from tests.test_r5_rules import r5_book


class DraftR5FeedbackTests(unittest.TestCase):
    def test_blocked_core_replacement_names_resident_and_missing_credit(self):
        book = r5_book()
        original = draft_schedule(book, STORE, max_seconds=5)
        person, = original["residents"]
        child = next(m for m in person["months"] if m["target"]["requirement_id"] == CHILD)
        geriatric = next(o for o in original["edit_options"] if o["requirement_id"] == GERI)

        result = validate_draft_change(book, STORE, original, {
            "kind": "edit", "resident": person["source"], "start": child["block_start"],
            "posting": geriatric["posting"], "institution": geriatric["institution"], "offering": geriatric["source"],
        })

        self.assertIsNone(result["draft"])
        self.assertEqual(result["issues"][0]["message"],
                         f"{person['name']} would still need 3 months of R5 Child & Adolescent Psychiatry.")
