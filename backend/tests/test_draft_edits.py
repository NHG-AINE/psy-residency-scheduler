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
from tests.test_r5_combined import add_history, combined_book, CHILD, GERI, LABEL
from tests.test_r5_rules import r5_book
from tests.test_workbook_import import structured_workbook_bytes
from workbook_import import parse_workbook


class DraftEditTests(unittest.TestCase):
    def edit(self, book, draft, start, option):
        return validate_draft_change(book, STORE, draft, {
            "kind": "edit", "resident": draft["residents"][0]["source"], "start": start,
            "posting": option["posting"], "institution": option["institution"], "offering": option["source"]})

    def test_manual_r5_core_splits_and_subsequent_moves(self):
        for longer, shorter, extended_site in ((GERI, CHILD, "SKH"), (CHILD, GERI, "IMH")):
            with self.subTest(longer=longer):
                book = r5_book()
                book["postings"]["core"].append({"residency_year": "R5", "posting": "SKH Geriatric Psychiatry",
                    "duration_months": "3", "source": {"sheet": "Postings", "row": 900}})
                roster = book["residents"][0]
                # Force the original three-month Geriatric and Child blocks so
                # the edit replaces the elective with a distinct core offering.
                book["requests"] = [
                    {"matched_resident_source": roster["source"], "posting_request": label, "period": period}
                    for label, period in [("CGH Geriatric Psychiatry", "Jul - Sep 2027"),
                                          ("NUH Child & Adolescent Psychiatry", "Oct - Dec 2027")]
                ]
                original = draft_schedule(book, STORE)
                person, = original["residents"]
                self.assertEqual([m["label"] for m in person["months"][::3]], ["CGH Geriatric Psychiatry",
                    "NUH Child & Adolescent Psychiatry", "IMH Forensic Psychiatry", "IMH Forensic Psychiatry"])
                extended = next(o for o in original["edit_options"] if o["requirement_id"] == longer
                                and o["institution"] == extended_site)
                edited = self.edit(book, original, "2028-01", extended)
                self.assertIsNotNone(edited["draft"], edited["issues"])
                saved = json.loads(json.dumps(edited["draft"]))
                assignments = [m["target"]["requirement_id"] for m in saved["residents"][0]["months"]]
                self.assertEqual((assignments.count(longer), assignments.count(shorter)), (9, 3))
                self.assertEqual(saved["residents"][0]["carryforward"], [])
                swap = {"resident": person["source"], "start": "2027-07", "destination": "2027-10", "kind": "swap"}
                swapped = validate_draft_change(book, STORE, saved, swap)
                self.assertIsNotNone(swapped["draft"], swapped["issues"])
                inserted = validate_draft_change(book, STORE, swapped["draft"], {
                    **swap, "start": "2028-01", "kind": "insert", "side": "before"})
                self.assertIsNotNone(inserted["draft"], inserted["issues"])
                last = inserted["draft"]["residents"][0]["months"][-1]
                alternate = next(o for o in original["edit_options"] if o["requirement_id"] == last["target"]["requirement_id"]
                                 and o["institution"] != last["target"]["institution"])
                reedited = self.edit(book, inserted["draft"], last["block_start"], alternate)
                self.assertIsNotNone(reedited["draft"], reedited["issues"])

                short_month = next(m for m in saved["residents"][0]["months"] if m["target"]["requirement_id"] == shorter)
                blocked = self.edit(book, saved, short_month["block_start"], extended)
                self.assertIsNone(blocked["draft"])
                self.assertEqual(blocked["issues"][0]["code"], "hard_constraint")

    def test_manual_r5_uses_combined_history_and_keeps_the_selected_carryforward(self):
        book = combined_book()
        add_history(book, [(f"2027-{month:02d}", LABEL) for month in range(1, 7)])
        for month in book["residents"][0]["postings"][4:]:
            month.update(status="loa", value="LOA")
        incoming = deepcopy(r1_book()["residents"][0])
        incoming.update(name="Incoming", mcr="SYN002", source={"sheet": book["target_sheet"], "row": 99})
        book["residents"].append(incoming)
        original = draft_schedule(book, STORE, max_seconds=5)
        geri = next(o for o in original["edit_options"] if o["requirement_id"] == GERI and o["institution"] == "CGH")
        result = self.edit(book, original, "2027-07", geri)
        self.assertIsNotNone(result["draft"], result["issues"])
        saved = json.loads(json.dumps(result["draft"]))
        edited, other = saved["residents"]
        self.assertEqual(edited["carryforward"], [{
            "requirement_id": GERI, "institution": "CGH", "label": "CGH Geriatric Psychiatry", "months": 2}])
        inpatient = other["months"][6]
        alternate = next(o for o in saved["edit_options"] if o["requirement_id"] == inpatient["target"]["requirement_id"]
                         and o["institution"] != inpatient["target"]["institution"])
        changed = validate_draft_change(book, STORE, saved, {
            "kind": "edit", "resident": other["source"], "start": inpatient["block_start"],
            "posting": alternate["posting"], "institution": alternate["institution"], "offering": alternate["source"]})
        self.assertIsNotNone(changed["draft"], changed["issues"])
        self.assertEqual(changed["draft"]["residents"][0], edited)

    def test_completed_nine_plus_three_history_leaves_no_elective_requirement(self):
        book = r5_book()
        labels = ["IMH Geriatric Psychiatry"] * 6 + ["CGH Geriatric Psychiatry"] * 3 + ["NUH Child & Adolescent Psychiatry"] * 3
        add_history(book, [(f"{2026 + (i + 6) // 12}-{(i + 6) % 12 + 1:02d}", label) for i, label in enumerate(labels)])
        edited = draft_schedule(book, STORE, max_seconds=5)
        person, = edited["residents"]
        self.assertEqual({m["status"] for m in person["months"]}, {"requirements_completed"})
        self.assertEqual(person["carryforward"], [])

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

    def test_reverse_swap_restoring_generated_draft_has_no_preview_warning(self):
        book = r2_book(2)
        draft = draft_schedule(book, STORE, max_seconds=5)
        person = draft["residents"][0]
        swap = {"kind": "swap", "resident": person["source"], "start": "2027-07", "destination": "2027-10"}
        changed = validate_draft_change(book, STORE, draft, swap)
        self.assertTrue(any(issue["code"] == "singleton_months" for issue in changed["issues"]))
        self.assertTrue(draft["singletons"])

        reverse = {**swap, "start": swap["destination"], "destination": swap["start"]}
        reversed_swap = validate_draft_change(book, STORE, json.loads(json.dumps(changed["draft"])), reverse)
        self.assertEqual(reversed_swap["issues"], [])
        self.assertEqual(reversed_swap["draft"]["edit_warnings"], [])
        self.assertEqual([p["months"] for p in reversed_swap["draft"]["residents"]],
                         [p["months"] for p in draft["residents"]])

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

    def test_r1_split_medicine_blocks_stay_editable_after_each_swap(self):
        book = r1_book(3)
        book["postings"]["core"] = [row for row in book["postings"]["core"] if row["posting"] not in {
            "TTSH General Medicine", "NNI Neurology", "NUH Medicine & Neurology"}]
        medicine, neurology = "SGH General Medicine", "SGH Neurology"
        for row in book["postings"]["core"]:
            if row["posting"] == medicine:
                row.update(max="2", allowed_block_lengths=[2, 4], fulfils_requirements=["General Medicine"],
                           additional_requirement=None, additional_credit_months=None)
            if row["posting"] == neurology:
                row["max"] = "1"
        for resident in book["residents"]:
            resident["postings"][3].update(status="loa", value="LOA")

        draft = draft_schedule(book, STORE, max_seconds=5)
        self.assertEqual(draft["capacity_overflows"], [])
        # Capacity forces the three schedules to cover each valid Neurology window.
        index = next(i for i, resident in enumerate(draft["residents"]) if resident["months"][2]["label"] == neurology)
        original = draft["residents"][index]
        other_index = next(i for i in range(3) if i != index)
        other = draft["residents"][other_index]
        active = [month for month in original["months"][:7] if month["status"] == "posting"]
        first, middle, last = (month["month"] for month in active[::2])
        starts = [first, first, middle, middle, last, last]
        self.assertEqual([month["block_start"] for month in active], starts)
        self.assertEqual(len({month["block_start"] for month in other["months"] if month["label"] == medicine}), 1)

        def apply(current, change):
            result = validate_draft_change(book, STORE, json.loads(json.dumps(current)), change)
            self.assertIsNotNone(result["draft"], result["issues"])
            return result["draft"]

        for start, destination, labels in (
            (first, middle, [neurology, medicine, medicine]),
            (middle, last, [medicine, medicine, neurology]),
        ):
            with self.subTest(start=start, destination=destination):
                swap = {"kind": "swap", "resident": original["source"], "start": start, "destination": destination}
                swapped = apply(draft, swap)
                inserted = apply(draft, {**swap, "kind": "insert", "side": "after"})
                self.assertEqual(inserted["residents"][index]["months"], swapped["residents"][index]["months"])
                edited = swapped["residents"][index]
                head = [month for month in edited["months"][:7] if month["status"] == "posting"]
                self.assertEqual([month["label"] for month in head], [label for label in labels for _ in range(2)])
                self.assertEqual([month["block_start"] for month in head], starts)
                self.assertEqual(edited["months"][3], original["months"][3])
                self.assertEqual(swapped["residents"][other_index]["months"], other["months"])

                inpatient = other["months"][7]
                option = next(o for o in draft["edit_options"]
                              if o["requirement_id"] == "r1.inpatient_psychiatry" and o["label"] != inpatient["label"])
                changed_other = apply(swapped, {"kind": "edit", "resident": other["source"], "start": inpatient["block_start"],
                    "posting": option["posting"], "institution": option["institution"], "offering": option["source"]})
                self.assertEqual(changed_other["residents"][index]["months"], edited["months"])
                reversed_draft = apply(changed_other, {**swap, "start": destination, "destination": start})
                self.assertEqual(reversed_draft["residents"][index]["months"], original["months"])
                self.assertEqual(reversed_draft["residents"][other_index]["months"], changed_other["residents"][other_index]["months"])

    def test_r1_swap_preserves_inpatient_carryforward(self):
        book = r1_book(3)
        for person in book["residents"]:
            for month in person["postings"][6:]:
                month.update(status="loa", value="LOA")
        for row in book["postings"]["core"]:
            if row["posting"] == "SGH General Medicine":
                row.update(max="2", allowed_block_lengths=[2, 4], fulfils_requirements=["General Medicine"],
                           additional_requirement=None, additional_credit_months=None)
            elif row["posting"] == "SGH Neurology":
                row["max"] = "1"
        book["postings"]["core"] = [row for row in book["postings"]["core"] if row["posting"]
            not in {"TTSH General Medicine", "NNI Neurology", "NUH Medicine & Neurology"}]
        draft = draft_schedule(book, STORE, max_seconds=5)
        index = next(i for i, person in enumerate(draft["residents"]) if person["months"][2]["label"] == "SGH Neurology")
        person = draft["residents"][index]
        change = {"kind": "swap", "resident": person["source"], "start": "2027-07", "destination": "2027-09"}
        # The same swap must preserve either valid future destination.
        for institution in ("NUH", "IMH"):
            with self.subTest(institution=institution):
                person["carryforward"] = [{"requirement_id": "r1.inpatient_psychiatry", "institution": institution, "months": 6}]
                result = validate_draft_change(book, STORE, draft, change)
                self.assertIsNotNone(result["draft"], result["issues"])
                updated = result["draft"]["residents"][index]
                self.assertEqual([month["label"] for month in updated["months"][:6]],
                                 ["SGH Neurology"] * 2 + ["SGH General Medicine"] * 4)
                self.assertEqual(updated["route"], person["route"])
                self.assertEqual(updated["carryforward"], person["carryforward"])

    def test_r1_cannot_swap_inpatient_before_medicine_and_neurology(self):
        book = r1_book()
        book["postings"]["core"] = [row for row in book["postings"]["core"]
            if row["posting"] in {"NUH Medicine & Neurology", "SGH Inpatient Psychiatry"}]
        draft = draft_schedule(book, STORE, max_seconds=5)
        person, = draft["residents"]
        blocked = validate_draft_change(book, STORE, draft, {"kind": "swap", "resident": person["source"],
            "start": "2027-07", "destination": "2028-01"})
        self.assertIsNone(blocked["draft"])
        self.assertEqual(blocked["issues"][0]["code"], "hard_constraint")

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

    def test_insert_unequal_r5_blocks_keeps_shared_credit_and_validates_final_order(self):
        book = r5_book()
        imported = parse_workbook(structured_workbook_bytes())
        book["postings"]["electives"].append(next(row for row in imported["postings"]["electives"]
                                                    if row.get("additional_requirement")))
        source = book["residents"][0]["source"]
        epip, child, geriatric = "IMH Child and EPIP", "KKH Child & Adolescent Psychiatry", "IMH Geriatric Psychiatry"
        book["requests"] = [{"posting_request": label, "period": period, "matched_resident_source": source}
                            for label, period in ((epip, "Jul - Dec 2027"),
                                                  (child, "Jan - Mar 2028"), (geriatric, "Apr - Jun 2028"))]
        draft = draft_schedule(book, STORE, max_seconds=5)
        original = deepcopy(draft)
        person, = draft["residents"]
        self.assertEqual([m["label"] for m in person["months"]], [epip] * 6 + [child] * 3 + [geriatric] * 3)
        change = {"kind": "insert", "resident": source, "start": "2028-04", "destination": "2027-07", "side": "before"}
        response = TestClient(app).post("/api/draft/validate-change", json={
            "workbook": book, "store": STORE.model_dump(), "draft": draft, "change": change})
        self.assertEqual(response.status_code, 200, response.text)
        for result, expected in (
            (response.json(), [geriatric] * 3 + [epip] * 6 + [child] * 3),
            (validate_draft_change(book, STORE, draft, {**change, "start": "2027-07", "destination": "2028-04", "side": "after"}),
             [child] * 3 + [geriatric] * 3 + [epip] * 6),
        ):
            self.assertIsNotNone(result["draft"], result["issues"])
            updated, = result["draft"]["residents"]
            self.assertEqual([month["label"] for month in updated["months"]], expected)
            self.assertEqual(updated["carryforward"], [])
            self.assertTrue(any(issue["code"] == "resident_requests" for issue in result["issues"]))
            self.assertEqual(len({month["block_start"] for month in updated["months"]}), 3)
        self.assertEqual(draft, original)

    def test_insert_across_leave_preserves_calendar_and_other_residents(self):
        book = r2_book(2)
        book["residents"][0]["postings"][1].update(status="loa", value="LOA")
        draft = draft_schedule(book, STORE, max_seconds=5)
        person, other = draft["residents"]
        first, second = (person["months"][i] for i in (0, 4))
        change = {"kind": "insert", "resident": person["source"], "start": second["block_start"],
                  "destination": first["block_start"], "side": "before"}
        result = validate_draft_change(book, STORE, draft, change)
        self.assertIsNotNone(result["draft"], result["issues"])
        updated, unchanged = result["draft"]["residents"]
        self.assertEqual(unchanged, other)
        self.assertEqual(updated["months"][1], person["months"][1])
        self.assertEqual([month["label"] for month in updated["months"][:7]],
                         [second["label"], None, second["label"], second["label"]] + [first["label"]] * 3)
        self.assertEqual(updated["carryforward"], person["carryforward"])

    def test_insert_rejects_invalid_r1_training_order(self):
        book = r1_book()
        draft = draft_schedule(book, STORE, max_seconds=5)
        person, = draft["residents"]
        result = validate_draft_change(book, STORE, draft, {
            "kind": "insert", "resident": person["source"], "start": person["months"][6]["block_start"],
            "destination": person["months"][0]["block_start"], "side": "before"})
        self.assertIsNone(result["draft"])
        self.assertEqual(result["issues"][0]["code"], "hard_constraint")
        self.assertIn("first six training months", result["issues"][0]["message"])
