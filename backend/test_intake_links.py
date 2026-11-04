import unittest
from copy import deepcopy

from fastapi.testclient import TestClient
from pydantic import ValidationError
from history_review import ReviewStore, evaluate_review
from intake_links import IntakeLinkStore, apply_intake_links
from main import app
from requirement_ledger import build_requirement_ledger
from test_workbook_import import workbook_bytes
from workbook_import import parse_workbook


def imported(rows, posting=None, year=2027, named_posting=None):
    def edit(w):
        sheet = w["Jul 2027 - Jun 2028"]
        for merged in list(sheet.merged_cells.ranges):
            sheet.unmerge_cells(str(merged))
        sheet["C2"] = "Residency Intake"
        for row, values in enumerate(rows, 3):
            for column, value in zip((4, 5, 6, 3), values):
                sheet.cell(row, column).value = value
            for column in range(7, 19):
                sheet.cell(row, column).value = (posting if row == 4 else named_posting if row == 3 else None) if column == 7 else None
    return parse_workbook(workbook_bytes(edit), year)


def store_for(workbook, slot="intake-2027-slot-02"):
    row = next(row for row in workbook["residents"] if row.get("slot_id") == slot)
    return IntakeLinkStore.model_validate({"version": 1, "links": [{"year": 2027, "slot_id": slot,
        "name": "Incoming Example", "mcr": "M900", "postings": [
            {key: posting[key] for key in ("month", "value", "status", "source")} for posting in row["postings"]]}]})


NAMED = ("Incoming Example", "M900", "R1", 2027)
PLACEHOLDER = ("Resident 2", None, "R1", 2027)


class IntakeLinkTests(unittest.TestCase):
    def test_explicit_link_collapses_rows_before_filling_even_when_original_exceeds_24(self):
        for placeholders in (23, 24):
            workbook = imported([NAMED] + [(f"Resident {n}", None, "R1", 2027) for n in range(2, placeholders + 2)])
            original = deepcopy(workbook)
            result = apply_intake_links(workbook, store_for(workbook))
            self.assertEqual(result["intake_links"][0]["status"], "applied")
            self.assertEqual(len(result["residents"]), 24)
            linked = [r for r in result["residents"] if r.get("slot_id") == "intake-2027-slot-02"]
            self.assertEqual(len(linked), 1)
            self.assertEqual(linked[0]["mcr"], "M900")
            self.assertFalse(linked[0]["is_intake_placeholder"])
            self.assertEqual(result["annual_sheets"], original["annual_sheets"])
            self.assertEqual(workbook, original)
            self.assertFalse(result["incoming_intake"]["fill_blocked"])
            self.assertNotIn("excess_intake", {i["code"] for i in result["issues"]})

    def test_reupload_reorder_missing_or_renamed_placeholder_and_year_switch_keep_slot(self):
        workbook = imported([NAMED, PLACEHOLDER], "TTSH General Medicine")
        store = store_for(workbook)
        for rows in ([NAMED, PLACEHOLDER], [PLACEHOLDER, NAMED], [NAMED]):
            result = apply_intake_links(imported(rows), store)
            linked = next(r for r in result["residents"] if r.get("mcr") == "M900")
            self.assertEqual(linked["slot_id"], "intake-2027-slot-02")
            self.assertEqual(len(result["residents"]), 24)
            self.assertEqual(linked["postings"][0]["value"], "TTSH General Medicine")
            self.assertEqual(sum(r.get("slot_id") == linked["slot_id"] for r in result["residents"]), 1)
        other = apply_intake_links(imported([NAMED], year=2026), store)
        self.assertEqual(other["intake_links"][0]["status"], "other_year")
        self.assertTrue(all(not r.get("slot_id", "").startswith("intake-2027") for r in other["residents"]))
        restored = apply_intake_links(workbook, store)
        self.assertEqual(restored["intake_links"][0]["status"], "applied")
        ledger = build_requirement_ledger(restored, ReviewStore(version=1, decisions=[]))
        named = next(r for r in ledger["residents"] if r["mcr"] == "M900")
        self.assertTrue(named["identity_safe"])
        self.assertEqual(named["months"], [])
        self.assertTrue(all(r["expected_months"] == 0 for r in named["requirements"]))
        # A retained slot posting can be reviewed without requiring a fabricated Excel source.
        self.assertTrue(evaluate_review(restored, ReviewStore(version=1, decisions=[]), "timetable")["entries"])

    def test_changed_identity_intake_or_duplicates_stay_reviewable_and_unapplied(self):
        store = store_for(imported([NAMED, PLACEHOLDER]))
        variants = [[("Different Name", "M900", "R1", 2027), PLACEHOLDER],
                    [("Incoming Example", "M901", "R1", 2027), PLACEHOLDER],
                    [("Incoming Example", "M900", "R1,R2", 2027), PLACEHOLDER],
                    [("Incoming Example", "M900", "R1", 2026), PLACEHOLDER],
                    [PLACEHOLDER], [NAMED, NAMED, PLACEHOLDER]]
        for rows in variants:
            with self.subTest(rows=rows):
                result = apply_intake_links(imported(rows), store)
                self.assertEqual(result["intake_links"][0]["status"], "needs_review")
                self.assertTrue(all(not (r.get("mcr") and r.get("slot_id")) for r in result["residents"]))
        self.assertEqual(len(store.links), 1)

    def test_conflicting_slot_or_named_postings_are_not_overwritten(self):
        store = store_for(imported([NAMED, PLACEHOLDER], "TTSH General Medicine"))
        for value, on_named in (("SGH General Medicine", True), ("LOA", True), ("SGH General Medicine", False)):
            workbook = imported([NAMED, PLACEHOLDER], value if not on_named else None,
                                named_posting=value if on_named else None)
            original = deepcopy(workbook)
            result = apply_intake_links(workbook, store)
            self.assertEqual(result["intake_links"][0]["status"], "needs_review")
            self.assertIn("conflict", result["intake_links"][0]["message"])
            self.assertEqual(workbook, original)
            self.assertEqual(result["annual_sheets"], original["annual_sheets"])

    def test_strict_store_validation_rejects_duplicate_scopes_and_bad_snapshots(self):
        valid = store_for(imported([NAMED, PLACEHOLDER])).model_dump()
        for change in (lambda s: s["links"].append(deepcopy(s["links"][0])),
                       lambda s: s["links"][0].update(slot_id="intake-2026-slot-02"),
                       lambda s: s["links"][0]["postings"][0].update(month="2026-07"),
                       lambda s: s["links"][0]["postings"][0].update(status="loa"),
                       lambda s: s["links"][0]["postings"].append(deepcopy(s["links"][0]["postings"][0]))):
            value = deepcopy(valid); change(value)
            with self.assertRaises(ValidationError):
                IntakeLinkStore.model_validate(value)
        with TestClient(app) as client:
            result = client.post("/api/intake-links", json={"workbook": imported([NAMED, PLACEHOLDER]), "store": valid})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["intake_links"][0]["status"], "applied")
            self.assertEqual(client.post("/api/intake-links", json={"workbook": {}, "store": valid}).status_code, 422)
