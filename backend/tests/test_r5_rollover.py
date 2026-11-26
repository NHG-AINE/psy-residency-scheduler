from collections import Counter
from datetime import date
from itertools import groupby
import unittest

from draft_edits import validate_draft_change
from requirement_ledger import build_requirement_ledger, programme_requirements_completed
from scheduler import draft_schedule
from tests.rollover_fixtures import following_year
from tests.test_r1_solver import STORE
from tests.test_r5_combined import CHILD, COMBINED, GERI, LABEL, add_history, combined_book
from tests.test_r5_rules import r5_book
from tests.test_workbook_import import structured_workbook_bytes
from workbook_import import parse_workbook


CHILD_SITE, OTHER_CHILD = "IMH Child & Adolescent Psychiatry", "NUH Child & Adolescent Psychiatry"
GERI_SITE, OTHER_GERI = "IMH Geriatric Psychiatry", "CGH Geriatric Psychiatry"
ELECTIVE = "r5.elective"
FLEX, SIX_ONLY, THREE_ONLY = "IMH General Psychiatry", "NUH General and Community Psychiatry", "TTSH Psychogeriatrics"
MIXED = {"IMH Child and EPIP": CHILD, "CGH Geriatric elective": GERI}


def next_year(book, prefix, leave=False):
    """Place a draft prefix at the end of the year to test a June cutoff."""
    recorded = list(prefix)
    if leave:
        recorded.append({"status": "loa"})
    dates = [m["month"] for m in book["months"]]
    following = following_year(book, [{**m, "month": date}
                                     for m, date in zip(recorded, dates[-len(recorded):])], "R5")
    if leave:
        following["residents"][0]["postings"][0].update(status="loa", value="LOA")
    return following


class R5RolloverTests(unittest.TestCase):
    def test_interrupted_combined_block_earns_credits_on_completion(self):
        other_site = "IMH Child and Geriatric Psychiatry"
        for tail, complete, conflict in (([LABEL] * 2, True, False), ([LABEL], False, False),
                                          ([other_site], False, True)):
            with self.subTest(tail=tail):
                book = combined_book()
                book["postings"]["core"].append({**book["postings"]["core"][-1], "posting": other_site,
                                                  "source": {"sheet": "Postings", "row": 901}})
                book["postings"]["electives"].append({"residency_year": "R5", "institution": "IMH",
                    "elective": "General Psychiatry", "remarks": [], "source": {"sheet": "Postings", "row": 902}})
                labels = [LABEL] * 4 + [FLEX + " (Elective)"] * 6 + tail
                add_history(book, [(f"{2026 + i // 12}-{i % 12 + 1:02d}", label)
                                   for i, label in enumerate(labels, start=6)])
                ledger, = build_requirement_ledger(book, STORE)["residents"]
                by_id = {r["requirement_id"]: r for r in ledger["requirements"]}
                self.assertEqual(by_id[CHILD]["expected_months"], 3 if complete else 0)
                self.assertEqual(by_id[GERI]["expected_months"], 3 if complete else 0)
                self.assertEqual(by_id[ELECTIVE]["expected_months"], 6)
                self.assertEqual("conflicting_partial_r5_history" in ledger["warnings"], conflict)
                if not conflict and not complete:
                    book["requests"] = [{"matched_resident_source": book["residents"][0]["source"],
                                         "posting_request": LABEL, "period": period}
                                        for period in ("Jul - Jul 2027", "Jul - Nov 2027")]
                result = draft_schedule(book, STORE, max_seconds=5)
                if conflict:
                    self.assertEqual(result["status"], "blocked")
                else:
                    self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
                    self.assertEqual(by_id[COMBINED]["expected_months"], 6 if complete else 5)
                    assigned = [m for m in result["residents"][0]["months"] if m["target"]]
                    self.assertEqual([m["label"] for m in assigned], [] if complete else [LABEL])
                    if assigned:
                        self.assertEqual(result["residents"][0]["requests"][0]["status"], "met")
                        self.assertEqual(result["residents"][0]["requests"][1]["reason_code"], "duration_mismatch")
                        following = following_year(book, result["residents"][0]["months"], "R5")
                        next_ledger, = build_requirement_ledger(following, STORE)["residents"]
                        self.assertTrue(programme_requirements_completed(next_ledger["months"]))

    def test_interrupted_core_can_return_after_a_completed_block_at_another_site(self):
        book = combined_book()
        labels = [GERI_SITE] + [OTHER_GERI] * 3 + [GERI_SITE] * 2 + [CHILD_SITE] * 6
        add_history(book, [(f"{2026 + i // 12}-{i % 12 + 1:02d}", label)
                           for i, label in enumerate(labels, start=6)])
        ledger, = build_requirement_ledger(book, STORE)["residents"]
        self.assertTrue(programme_requirements_completed(ledger["months"]))
        result = draft_schedule(book, STORE, max_seconds=5)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        self.assertTrue(all(month["status"] == "requirements_completed"
                            for month in result["residents"][0]["months"]))

    def test_edited_nine_month_core_resumes_second_site_after_june(self):
        book = r5_book()
        first, second, child = "CGH Geriatric Psychiatry", "IMH Geriatric Psychiatry", "NUH Child & Adolescent Psychiatry"
        source = book["residents"][0]["source"]
        book["requests"] = [{"matched_resident_source": source, "posting_request": label, "period": period}
                            for label, period in [(second, "Jan - Mar 2028"), (child, "Apr - Jun 2028")]]
        draft = draft_schedule(book, STORE, max_seconds=5)
        target = next(o for o in draft["edit_options"] if o["requirement_id"] == GERI and o["label"] == first)
        edited = validate_draft_change(book, STORE, draft, {
            "kind": "edit", "resident": source, "start": "2027-07", "posting": target["posting"],
            "institution": target["institution"], "offering": target["source"]})
        self.assertIsNotNone(edited["draft"], edited["issues"])
        months = edited["draft"]["residents"][0]["months"]
        self.assertEqual([m["label"] for m in months], [first] * 6 + [second] * 3 + [child] * 3)
        for cut in (7, 8):
            with self.subTest(cut=cut):
                following = next_year(book, months[:cut])
                ledger, = build_requirement_ledger(following, STORE)["residents"]
                self.assertEqual(ledger["warnings"], [])
                left = {r["requirement_id"]: r["remaining_months"] for r in ledger["requirements"]}
                result = draft_schedule(following, STORE, max_seconds=5)
                self.assertIn(result["status"], {"optimal", "feasible"}, result["skipped_residents"])
                assigned = [m for m in result["residents"][0]["months"] if m["target"]]
                self.assertEqual([m["label"] for m in assigned[:9-cut]], [second] * (9-cut))
                self.assertEqual([m["target"]["requirement_id"] for m in assigned], [GERI] * (9-cut) + [CHILD] * 3)
                self.assertEqual((left[GERI], left[CHILD], left["r5.elective"]), (9-cut, 3, 0))

    def rollover(self, book, months, cut, leave=False):
        following = next_year(book, months[:cut], leave)
        ledger, = build_requirement_ledger(following, STORE)["residents"]
        by_id = {r["requirement_id"]: r for r in ledger["requirements"]}
        result = draft_schedule(following, STORE, max_seconds=5)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["skipped_residents"])
        person, = result["residents"]
        self.assertEqual(person["carryforward"], [])
        if leave:
            self.assertEqual(person["months"][0]["status"], "loa")
        assigned = [m for m in person["months"] if m["target"]]
        self.assertEqual(len(assigned), 12 - cut)
        self.assertTrue(all(m["status"] == "requirements_completed" for m in person["months"][len(assigned) + leave:]))
        # The prefix only fixes the shortest possible unfinished block. An
        # unrecorded extension or a future site is free to change.
        prefix = months[:cut]
        last = prefix[-1]["label"]
        trailing = next((i for i, m in enumerate(reversed(prefix)) if m["label"] != last), cut)
        unit = 6 if last in {*MIXED, LABEL, SIX_ONLY} else 3
        remaining = -trailing % unit
        self.assertEqual([m["label"] for m in assigned[:remaining]], [last] * remaining)
        for evidence, check_complete in ((prefix, False), (prefix + assigned, True)):
            credits = Counter()
            for label, block in groupby(evidence, key=lambda m: m["label"]):
                cells = list(block)
                length = len(cells)
                if label == LABEL or label in MIXED:
                    if check_complete:
                        self.assertEqual(length, 6)
                    if length == 6:
                        credits.update({CHILD: 3, GERI: 3} if label == LABEL else {MIXED[label]: 3, ELECTIVE: 3})
                else:
                    if check_complete:
                        self.assertIn(length, (3, 6, 9))
                        if label == SIX_ONLY:
                            self.assertEqual(length, 6)
                    credits[cells[0]["target"]["requirement_id"]] += length
            if check_complete:
                final_credits = credits
                self.assertIn((credits[CHILD], credits[GERI], credits[ELECTIVE]),
                              ((3, 3, 6), (3, 6, 3), (6, 3, 3), (6, 6, 0), (3, 9, 0), (9, 3, 0)))
                self.assertEqual([credits[key] for key in (CHILD, GERI, ELECTIVE)],
                                 [by_id[key]["required_months"] for key in (CHILD, GERI, ELECTIVE)])
            else:
                for key in (CHILD, GERI, ELECTIVE):
                    self.assertEqual(by_id[key]["expected_months"], credits[key])
                self.assertEqual(sum(by_id[key]["required_months"] for key in (CHILD, GERI, ELECTIVE)), 12)
        return by_id, final_credits

    def requested_plan(self, catalogue, blocks, edit=None):
        book = combined_book()
        book["postings"]["electives"].extend(catalogue)
        labels = [label for label, length in blocks for _ in range(length)]
        book["requests"] = []
        offset = 0
        for label, length in blocks:
            period = [date.fromisoformat(month["month"] + "-01") for month in book["months"][offset:offset + length]]
            book["requests"].append({"matched_resident_source": book["residents"][0]["source"], "posting_request": label,
                                     "period": f"{period[0]:%b %Y} - {period[-1]:%b %Y}"})
            offset += length
        draft = draft_schedule(book, STORE, max_seconds=5)
        self.assertIn(draft["status"], {"optimal", "feasible"}, draft["blockers"])
        person, = draft["residents"]
        self.assertEqual([m["label"] for m in person["months"]], labels)
        if edit:
            start, label = edit
            target = next(o for o in draft["edit_options"] if o["residency_year"] == "R5" and o["label"] == label)
            result = validate_draft_change(book, STORE, draft, {
                "kind": "edit", "resident": person["source"], "start": person["months"][start]["month"],
                "posting": target["posting"], "institution": target["institution"], "offering": target["source"]})
            self.assertIsNotNone(result["draft"], result["issues"])
            person, = result["draft"]["residents"]
            self.assertEqual(person["months"][start]["label"], label)
        return book, person["months"]

    def test_supported_plans_at_each_june_boundary(self):
        def add_geriatric_credit(workbook):
            workbook["Postings"].append(("R5", "Elective", "CGH", "Geriatric elective", 6, 6,
                                         "Elective", "Geriatric Psychiatry", 3))
        catalogue = [e for e in parse_workbook(structured_workbook_bytes(add_geriatric_credit))["postings"]["electives"]
                     if e["residency_year"] == "R5" and "Unsupported" not in e["elective"]]
        child_mix, geri_mix = MIXED
        plans = [
            (((SIX_ONLY, 6), (CHILD_SITE, 3), (GERI_SITE, 3)), None),
            (((CHILD_SITE, 3), (FLEX, 3), (GERI_SITE, 3), (THREE_ONLY, 3)), None),
            (((THREE_ONLY, 3), (THREE_ONLY, 3), (GERI_SITE, 3), (CHILD_SITE, 3)), None),
            (((CHILD_SITE, 6), (FLEX, 3), (GERI_SITE, 3)), None),
            (((GERI_SITE, 6), (FLEX, 3), (CHILD_SITE, 3)), None),
            (((CHILD_SITE, 6), (GERI_SITE, 6)), None),
            (((LABEL, 6), (SIX_ONLY, 6)), None),
            (((child_mix, 6), (GERI_SITE, 3), (FLEX, 3)), None),
            (((CHILD_SITE, 3), (child_mix, 6), (GERI_SITE, 3)), None),
            (((LABEL, 6), (geri_mix, 6)), None),
            (((child_mix, 6), (geri_mix, 6)), None),
            (((GERI_SITE, 6), (child_mix, 6)), None),
            (((SIX_ONLY, 6), (CHILD_SITE, 3), (GERI_SITE, 3)), (0, OTHER_CHILD)),
            (((GERI_SITE, 3), (SIX_ONLY, 6), (CHILD_SITE, 3)), (3, OTHER_GERI)),
            (((GERI_SITE, 3), (CHILD_SITE, 3), (SIX_ONLY, 6)), (6, OTHER_GERI)),
            (((SIX_ONLY, 6), (GERI_SITE, 3), (CHILD_SITE, 3)), (0, GERI_SITE)),
            (((SIX_ONLY, 6), (LABEL, 6)), (0, OTHER_GERI)),
            (((LABEL, 6), (SIX_ONLY, 6)), (6, OTHER_CHILD)),
        ]
        for blocks, edit in plans:
            with self.subTest(blocks=blocks, edit=edit):
                book, months = self.requested_plan(catalogue, blocks, edit)
                for cut in range(1, 13):
                    with self.subTest(cut=cut):
                        by_id, credits = self.rollover(book, months, cut)
                        if edit and blocks[0][1] == 6 and blocks[0][0] != LABEL and cut == 6:
                            self.assertEqual(by_id[ELECTIVE]["remaining_months"], 3)
                            self.assertEqual(credits[ELECTIVE], 3)
                        if edit == (3, OTHER_GERI) and cut in (4, 5):
                            self.assertEqual(by_id[GERI]["required_months"], 6)
                            self.assertEqual(by_id[ELECTIVE]["remaining_months"], 3)
                for cut in (1, 7):
                    with self.subTest(cut=cut, leave=True):
                        self.rollover(book, months, cut, leave=True)

    def test_interrupted_core_conflicts_even_if_all_twelve_months_are_recorded(self):
        book, months = self.requested_plan([], [(GERI_SITE, 6), (CHILD_SITE, 6)])
        following = next_year(book, months)
        history = following["annual_sheets"][-1]["residents"][0]["postings"]
        history[0]["value"] = OTHER_GERI
        ledger, = build_requirement_ledger(following, STORE)["residents"]
        self.assertFalse(programme_requirements_completed(ledger["months"]))
        result = draft_schedule(following, STORE, max_seconds=5)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("conflicting_partial_r5_history", [r["code"] for r in result["skipped_residents"][0]["reasons"]])
        recorded = [m["target"]["label"] for m in ledger["months"] if m.get("requirement_year") == "R5"]
        self.assertEqual(recorded, [OTHER_GERI] + [GERI_SITE] * 5 + [CHILD_SITE] * 6)
        self.assertIn("conflicting_partial_r5_history", ledger["warnings"])
