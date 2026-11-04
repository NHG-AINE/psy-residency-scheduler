import unittest
from copy import deepcopy
from itertools import permutations
from fastapi.testclient import TestClient
from pydantic import ValidationError
from main import app
from history_review import ReviewStore, evaluate_review
from workbook_import import parse_workbook
from test_workbook_import import workbook_bytes


def workbook():
    def resident(name, mcr, row, months):
        return {"name": name, "mcr": mcr, "residency_year": "R3", "match_status": "matched",
                "source": {"sheet": "Earlier", "row": row},
                "postings": [{"month": month, "value": value, "status": "posting" if value else "blank",
                              "source": {"sheet": "Earlier", "row": row, "column": chr(70 + i)}}
                             for i, (month, value) in enumerate(months)]}
    return {"histories": [{"residents": [resident("Alex Example", "M001", 3, [
        ("2025-05", "Old department (Elective)"), ("2025-06", "Old department (Elective)")])]},
        {"residents": [resident("Alex Example", " m001 ", 7, [("2025-07", "Old department (Elective)"),
            ("2025-08", None), ("2025-09", "Old department (Elective)")])]}],
        "issues": [], "postings": {"core": [{"posting": "SITE Department", "residency_year": "R2",
            "duration_months": "3", "remarks": None, "source": {"sheet": "Reference", "row": 3}}],
        "electives": [{"institution": "SITE", "elective": "Department", "residency_year": "R2",
            "remarks": [], "source": {"sheet": "Reference", "row": 4, "column": "A"}},
            {"institution": "OTHER", "elective": "Other Department", "residency_year": "R5",
             "remarks": [], "source": {"sheet": "Reference", "row": 5, "column": "B"}}]}}


def evaluate(book, decisions=None):
    return evaluate_review(book, ReviewStore.model_validate({"version": 1, "decisions": decisions or []}))


def target(candidate):
    return {key: candidate[key] for key in ("key", "signature")}


def personal(result, index=0, year="R2", candidate=1):
    return {"kind": "resident", "context": deepcopy(result["entries"][index]["context"]),
            "target": target(result["catalogue"][candidate]), "requirement_year": year}


def alias(result, candidate=1):
    entry = result["entries"][0]
    return {"kind": "alias", "context": {"label": entry["months"][0]["value"],
            "recorded_year": entry["context"]["recorded_year"], "category": "elective"},
            "target": target(result["catalogue"][candidate])}


class HistoryReviewTests(unittest.TestCase):
    def clear_workbook(self):
        book = workbook()
        book["histories"] = book["histories"][:1]
        resident = book["histories"][0]["residents"][0]
        resident["residency_year"] = "R1"
        labels = ["SITE Ward", "SITE Medicine", "SITE Neurology"]
        resident["postings"] = [{"month": f"2025-{i + 5:02d}", "value": label, "status": "posting",
                                  "source": {"sheet": "Earlier", "row": 3, "column": chr(70 + i)}}
                                 for i, label in enumerate(labels)]
        book["postings"] = {"core": [{"posting": label, "residency_year": "R1", "duration_months": "3",
                                      "remarks": None, "source": {"sheet": "Reference", "row": 20 + i}}
                                     for i, label in enumerate(labels)], "electives": []}
        return book

    def cross_year_workbook(self):
        book = self.clear_workbook()
        later = deepcopy(book["postings"]["core"][0])
        later.update(residency_year="R4", source={"sheet": "Reference", "row": 70})
        book["postings"]["core"].append(later)
        book["postings"]["electives"] = [{"institution": "SITE", "elective": "Ward", "residency_year": "R2",
                                           "remarks": [], "source": {"sheet": "Reference", "row": 71, "column": "B"}}]
        return book

    def test_combined_recorded_years_resolve_one_elective_without_rewriting_history(self):
        book = self.cross_year_workbook()
        resident = book["histories"][0]["residents"][0]
        resident["residency_year"] = "R2,R3"
        resident["postings"][0]["value"] = " SITE Ward ( eLeCtIvE ) "
        original = deepcopy(book)
        result = evaluate(book)
        entry = result["entries"][0]
        self.assertEqual(entry["review"]["status"], "automatic_match")
        self.assertEqual(entry["review"]["target"]["residency_year"], "R2")
        self.assertEqual(entry["review"]["target"]["category"], "elective")
        self.assertEqual(entry["recorded_year"], "R2,R3")
        self.assertEqual(entry["months"][0]["value"], " SITE Ward ( eLeCtIvE ) ")
        self.assertNotIn("mixed_recorded_years", entry["match"]["reasons"])
        self.assertIsNone(entry["review"]["requirement_year"])
        self.assertEqual(result["decisions"], [])
        self.assertEqual(book, original)
        reviewed = evaluate(book, [personal(result, year="R2", candidate=4)])["entries"][0]
        self.assertEqual(reviewed["review"]["status"], "reviewed")
        self.assertNotIn("mixed_recorded_years", reviewed["match"]["reasons"])

    def test_combined_recorded_context_keeps_multiple_or_absent_candidates_in_review(self):
        book = self.cross_year_workbook()
        resident = book["histories"][0]["residents"][0]
        resident["residency_year"] = "R2,R3"
        resident["postings"][0]["value"] += " (Elective)"
        second_year = deepcopy(book["postings"]["electives"][0])
        second_year.update(residency_year="R3", source={"sheet": "Reference", "row": 99, "column": "B"})
        book["postings"]["electives"].append(second_year)
        entry = evaluate(book)["entries"][0]
        self.assertEqual(entry["match"]["status"], "ambiguous")
        self.assertEqual(entry["review"]["status"], "unreviewed")
        self.assertEqual(len(entry["match"]["candidates"]), 2)
        self.assertIn("mixed_recorded_years", entry["match"]["reasons"])
        resident["residency_year"] = "R4,R5"
        entry = evaluate(book)["entries"][0]
        self.assertNotEqual(entry["review"]["status"], "automatic_match")
        self.assertIn("multiple_catalogue_candidates", entry["match"]["reasons"])
        self.assertIsNone(entry["match"]["selected_candidate"])

    def test_combined_recorded_context_applies_core_precedence_and_preserves_alternatives(self):
        book = self.cross_year_workbook()
        resident = book["histories"][0]["residents"][0]
        resident["residency_year"] = "R2,R3"
        book["postings"]["core"][0]["residency_year"] = "R2"
        book["postings"]["electives"][0]["residency_year"] = "R3"
        entry = evaluate(book)["entries"][0]
        self.assertEqual(entry["review"]["status"], "automatic_match")
        self.assertEqual(entry["review"]["target"]["category"], "core")
        self.assertEqual(entry["review"]["target"]["residency_year"], "R2")
        self.assertEqual(len(entry["match"]["candidates"]), 3)
        self.assertEqual(entry["match"]["reasons"], ["catalogue_alternatives"])

    def test_combined_recorded_context_does_not_bypass_catalogue_identity_credit_or_saved_review(self):
        for scenario, reason in (("unknown_catalogue", "catalogue_year_unknown"), ("mixed_catalogue", "mixed_catalogue_years"),
                                 ("remediation", "remediation_credit_review"),
                                 ("stale", "catalogue_target_changed_or_missing"), ("conflict", "conflicting_saved_decisions")):
            with self.subTest(scenario=scenario):
                book = self.clear_workbook()
                resident = book["histories"][0]["residents"][0]
                resident["residency_year"] = "R1,R3"
                initial = evaluate(book)
                self.assertEqual(initial["entries"][0]["review"]["status"], "automatic_match")
                decisions = []
                if scenario in {"unknown_catalogue", "mixed_catalogue"}:
                    book["postings"]["core"][0]["residency_year"] = None if scenario == "unknown_catalogue" else "R1,R3"
                elif scenario == "remediation":
                    resident["postings"][0]["value"] += " (Remediation)"
                else:
                    decision = personal(initial, year="R1", candidate=0)
                    if scenario == "stale":
                        book["postings"]["core"][0]["duration_months"] = "4"
                        decisions = [decision]
                    else:
                        decisions = [decision, decision]
                entry = evaluate(book, decisions)["entries"][0]
                self.assertNotEqual(entry["review"]["status"], "automatic_match")
                self.assertIn(reason, entry["match"]["reasons"] + entry["review"]["reasons"])
                self.assertEqual(entry["recorded_year"], "R1,R3")

    def test_unique_same_year_core_precedes_electives_unless_explicitly_marked(self):
        book = self.cross_year_workbook()
        book["histories"][0]["residents"][0]["residency_year"] = "R2"
        book["postings"]["core"][0]["residency_year"] = "R2"
        later = deepcopy(book["postings"]["electives"][0])
        later.update(residency_year="R5", source={"sheet": "Reference", "row": 90, "column": "B"})
        book["postings"]["electives"].append(later)
        original = deepcopy(book)
        result = evaluate(book)
        entry = result["entries"][0]
        self.assertEqual(entry["review"]["status"], "automatic_match")
        self.assertEqual(entry["review"]["target"]["category"], "core")
        self.assertEqual(entry["review"]["target"]["residency_year"], "R2")
        self.assertEqual(len(entry["match"]["candidates"]), 4)
        self.assertEqual(entry["match"]["reasons"], ["catalogue_alternatives"])
        self.assertEqual(result["decisions"], [])
        self.assertIsNone(entry["review"]["requirement_year"])
        self.assertEqual(book, original)
        for marker in ("(Elective)", " ( eLeCtIvE ) "):
            marked = deepcopy(book)
            marked["histories"][0]["residents"][0]["postings"][0]["value"] += marker
            entry = evaluate(marked)["entries"][0]
            self.assertEqual(entry["review"]["status"], "automatic_match")
            self.assertEqual(entry["review"]["target"]["category"], "elective")
            self.assertEqual(entry["review"]["target"]["residency_year"], "R2")
            self.assertTrue(all(c["category"] == "elective" for c in entry["match"]["candidates"]))

    def test_duplicate_cores_or_electives_without_core_and_uncertain_catalogue_years_stay_open(self):
        for scenario, reason in (("cores", "multiple_catalogue_candidates"), ("electives", "multiple_catalogue_candidates"),
                                 ("unknown_alternative_year", "catalogue_year_unknown"), ("mixed_alternative_year", "mixed_catalogue_years")):
            with self.subTest(scenario=scenario):
                book = self.cross_year_workbook()
                resident = book["histories"][0]["residents"][0]
                if scenario == "cores":
                    duplicate = deepcopy(book["postings"]["core"][0])
                    duplicate["source"]["row"] = 99
                    book["postings"]["core"].append(duplicate)
                elif scenario == "electives":
                    resident["residency_year"] = "R2"
                    duplicate = deepcopy(book["postings"]["electives"][0])
                    duplicate["source"]["row"] = 99
                    book["postings"]["electives"].append(duplicate)
                else:
                    book["postings"]["electives"][0]["residency_year"] = None if scenario == "unknown_alternative_year" else "R2,R5"
                entry = evaluate(book)["entries"][0]
                self.assertNotEqual(entry["review"]["status"], "automatic_match")
                self.assertIsNone(entry["match"]["selected_candidate"])
                self.assertIn(reason, entry["match"]["reasons"])

    def test_unique_recorded_year_resolves_core_or_elective_and_keeps_all_alternatives(self):
        for year, category in (("R1", "core"), ("R4", "core"), ("R2", "elective")):
            with self.subTest(year=year):
                book = self.cross_year_workbook()
                book["histories"][0]["residents"][0]["residency_year"] = year
                original = deepcopy(book)
                entry = evaluate(book)["entries"][0]
                self.assertEqual(entry["review"]["status"], "automatic_match")
                self.assertEqual(entry["review"]["target"]["residency_year"], year)
                self.assertEqual(entry["review"]["target"]["category"], category)
                self.assertEqual(len(entry["match"]["candidates"]), 3)
                self.assertEqual({c["residency_year"] for c in entry["match"]["candidates"]}, {"R1", "R2", "R4"})
                self.assertEqual(entry["match"]["reasons"], ["catalogue_alternatives"])
                self.assertIsNone(entry["review"]["requirement_year"])
                if year == "R2":
                    self.assertEqual(entry["match"]["candidates"][0]["category"], "core")
                    self.assertEqual(entry["match"]["selected_candidate"]["category"], "elective")
                self.assertEqual(book, original)

    def test_explicit_elective_marker_excludes_core_even_when_core_matches_recorded_year(self):
        book = self.cross_year_workbook()
        book["histories"][0]["residents"][0]["postings"][0]["value"] += " (Elective)"
        first = evaluate(book)["entries"][0]
        self.assertNotEqual(first["review"]["status"], "automatic_match")
        self.assertTrue(all(c["category"] == "elective" for c in first["match"]["candidates"]))
        same_year = deepcopy(book["postings"]["electives"][0])
        same_year.update(residency_year="R1", source={"sheet": "Reference", "row": 72, "column": "B"})
        book["postings"]["electives"].append(same_year)
        entry = evaluate(book)["entries"][0]
        self.assertEqual(entry["review"]["status"], "automatic_match")
        self.assertEqual(entry["review"]["target"]["category"], "elective")
        self.assertEqual(entry["review"]["target"]["residency_year"], "R1")
        self.assertEqual(len(entry["match"]["candidates"]), 2)

    def test_cross_year_resolution_does_not_bypass_uncertainty_or_saved_decisions(self):
        for scenario in ("mixed", "missing", "outside", "same_year_collision", "remediation", "stale", "conflict"):
            with self.subTest(scenario=scenario):
                book = self.cross_year_workbook()
                initial = evaluate(book)
                decisions = []
                resident = book["histories"][0]["residents"][0]
                if scenario in {"mixed", "missing", "outside"}:
                    resident["residency_year"] = {"mixed": "R1,R4", "missing": None, "outside": "R1"}[scenario]
                    if scenario == "outside":
                        book["postings"]["core"][0]["residency_year"] = "R2"
                elif scenario == "same_year_collision":
                    duplicate = deepcopy(book["postings"]["core"][0])
                    duplicate["source"]["row"] = 99
                    book["postings"]["core"].append(duplicate)
                elif scenario == "remediation":
                    resident["postings"][0]["value"] += " (Remediation)"
                else:
                    decision = personal(initial, year="R1", candidate=0)
                    if scenario == "stale":
                        book["postings"]["core"][0]["duration_months"] = "4"
                        decisions = [decision]
                    else:
                        decisions = [decision, decision]
                entry = evaluate(book, decisions)["entries"][0]
                self.assertNotEqual(entry["review"]["status"], "automatic_match")
                self.assertEqual(len(entry["match"]["candidates"]), 4 if scenario == "same_year_collision" else 3)
                self.assertTrue(entry["match"]["reasons"] or entry["review"]["reasons"])

    def test_unsafe_identities_can_match_labels_without_merging_or_assigning_personal_credit(self):
        book = self.clear_workbook()
        resident = book["histories"][0]["residents"][0]
        resident["match_status"] = "ambiguous"
        duplicate = deepcopy(resident)
        duplicate["source"]["row"] = 44
        for posting in duplicate["postings"]:
            posting["source"]["row"] = 44
        book["histories"][0]["residents"].append(duplicate)
        book["issues"] = [{"code": "duplicate_mcr", "records": [{"source": resident["source"]}, {"source": duplicate["source"]}]}]
        original = deepcopy(book)
        result = evaluate(book)
        self.assertEqual(len(result["entries"]), 6)
        self.assertEqual(len({entry["id"] for entry in result["entries"]}), 6)
        for entry in result["entries"]:
            self.assertFalse(entry["identity_safe"])
            self.assertEqual(entry["review"]["status"], "automatic_match")
            self.assertNotIn("identity_review_required", entry["review"]["reasons"])
            self.assertEqual(len(entry["months"]), 1)
            self.assertIsNone(entry["review"]["requirement_year"])
        self.assertEqual(result["decisions"], [])
        self.assertEqual(book, original)

    def test_unsafe_identity_does_not_hide_unknown_labels_or_apply_saved_personal_decisions(self):
        book = self.clear_workbook()
        initial = evaluate(book)
        decision = personal(initial, year="R1", candidate=0)
        resident = book["histories"][0]["residents"][0]
        resident["match_status"] = "ambiguous"
        result = evaluate(book, [decision])
        entry = result["entries"][0]
        self.assertEqual(entry["match"]["status"], "matched")
        self.assertEqual(entry["review"]["status"], "needs_review")
        self.assertIsNone(entry["review"]["target"])
        self.assertIsNone(entry["review"]["requirement_year"])
        self.assertIn("identity_review_required", result["decisions"][0]["reasons"])
        self.assertEqual(result["decisions"][0]["status"], "needs_review")
        resident["postings"][0]["value"] = "Unrecognized historical wording"
        unknown = evaluate(book)["entries"][0]
        self.assertFalse(unknown["identity_safe"])
        self.assertEqual(unknown["review"]["status"], "unreviewed")
        self.assertIn("no_catalogue_match", unknown["match"]["reasons"])
        self.assertNotIn("identity_review_required", unknown["review"]["reasons"])

    def test_clear_exact_r1_matches_are_automatic_without_persisted_decisions_or_credit(self):
        book = self.clear_workbook()
        original = deepcopy(book)
        result = evaluate(book)
        self.assertEqual(len(result["entries"]), 3)
        for entry in result["entries"]:
            self.assertEqual(entry["review"]["status"], "automatic_match")
            self.assertEqual(entry["review"]["target"]["label"], entry["months"][0]["value"])
            self.assertIsNone(entry["review"]["requirement_year"])
            self.assertEqual(entry["recorded_year"], "R1")
            self.assertEqual(entry["review"]["reasons"], [])
        self.assertEqual(result["decisions"], [])
        self.assertEqual(book, original)

    def test_exact_elective_marker_is_informational_for_automatic_matching(self):
        book = workbook()
        book["histories"] = book["histories"][:1]
        resident = book["histories"][0]["residents"][0]
        resident["residency_year"] = "R2"
        for posting in resident["postings"]:
            posting["value"] = "SITE Department (Elective)"
        entry = evaluate(book)["entries"][0]
        self.assertEqual(entry["match"]["reasons"], ["explicit_elective"])
        self.assertEqual(entry["review"]["status"], "automatic_match")
        self.assertEqual(entry["review"]["target"]["category"], "elective")

    def test_uncertain_years_ambiguity_and_remediation_keep_review_reasons(self):
        for scenario, reason in (("mixed_recorded", "mixed_recorded_years"), ("missing_recorded", "recorded_year_unknown"),
                                 ("different_year", "requirement_year_review"), ("mixed_catalogue", "mixed_catalogue_years"),
                                 ("missing_catalogue", "catalogue_year_unknown"), ("ambiguous", "multiple_catalogue_candidates"),
                                 ("remediation", "remediation_credit_review")):
            with self.subTest(scenario=scenario):
                book = self.clear_workbook()
                resident = book["histories"][0]["residents"][0]
                if scenario in {"mixed_recorded", "missing_recorded", "different_year"}:
                    resident["residency_year"] = {"mixed_recorded": "R1,R2", "missing_recorded": None, "different_year": "R1"}[scenario]
                    if scenario == "different_year":
                        book["postings"]["core"][0]["residency_year"] = "R3"
                    if scenario == "mixed_recorded":
                        second_year = deepcopy(book["postings"]["core"][0])
                        second_year.update(residency_year="R2", source={"sheet": "Reference", "row": 99})
                        book["postings"]["core"].append(second_year)
                elif scenario in {"mixed_catalogue", "missing_catalogue"}:
                    book["postings"]["core"][0]["residency_year"] = "R1,R2" if scenario == "mixed_catalogue" else None
                elif scenario == "ambiguous":
                    duplicate = deepcopy(book["postings"]["core"][0])
                    duplicate["source"]["row"] = 80
                    book["postings"]["core"].append(duplicate)
                elif scenario == "remediation":
                    resident["postings"][0]["value"] += " (Remediation)"
                else:
                    resident["match_status"] = "ambiguous"
                entry = evaluate(book)["entries"][0]
                self.assertNotEqual(entry["review"]["status"], "automatic_match")
                self.assertIn(reason, entry["match"]["reasons"] + entry["review"]["reasons"])

    def test_stale_conflicting_and_valid_saved_decisions_take_precedence_over_auto_match(self):
        book = self.clear_workbook()
        initial = evaluate(book)
        decision = personal(initial, year="R1", candidate=0)
        manual = evaluate(book, [decision])["entries"][0]
        self.assertEqual(manual["review"]["status"], "reviewed")
        self.assertEqual(manual["review"]["requirement_year"], "R1")
        decision["requirement_year"] = None
        self.assertEqual(evaluate(book, [decision])["entries"][0]["review"]["status"], "label_confirmed")
        conflict = evaluate(book, [decision, decision])["entries"][0]
        self.assertEqual(conflict["match"]["status"], "matched")
        self.assertEqual(conflict["review"]["status"], "needs_review")
        self.assertIn("conflicting_saved_decisions", conflict["review"]["reasons"])
        book["postings"]["core"][0]["duration_months"] = "4"
        stale = evaluate(book, [decision])["entries"][0]
        self.assertEqual(stale["match"]["status"], "matched")
        self.assertEqual(stale["review"]["status"], "needs_review")
        self.assertIn("catalogue_target_changed_or_missing", stale["review"]["reasons"])

    def test_unsafe_identity_keeps_wording_alias_applied_without_label_identity_warning(self):
        book = self.clear_workbook()
        initial = evaluate(book)
        entry = initial["entries"][0]
        decision = {"kind": "alias", "context": {"label": entry["months"][0]["value"], "recorded_year": "r1", "category": "core"},
                    "target": target(initial["catalogue"][0])}
        book["histories"][0]["residents"][0]["match_status"] = "ambiguous"
        result = evaluate(book, [decision])
        self.assertEqual(result["entries"][0]["review"]["status"], "label_confirmed")
        self.assertNotIn("identity_review_required", result["entries"][0]["review"]["reasons"])
        self.assertFalse(result["entries"][0]["identity_safe"])
        self.assertEqual(result["decisions"][0]["status"], "applied")

    def test_groups_consecutive_cross_tab_runs_without_merging_separated_periods(self):
        book = workbook()
        result = evaluate(book)
        self.assertEqual([len(e["months"]) for e in result["entries"]], [3, 1])
        self.assertEqual(result["entries"][0]["months"][-1]["month"], "2025-07")
        book["histories"][1]["residents"][0]["residency_year"] = "R3,R4"
        self.assertEqual([len(e["months"]) for e in evaluate(book)["entries"]], [2, 1, 1])

    def test_reupload_row_reorder_and_catalogue_source_moves_preserve_decisions(self):
        book = workbook()
        result = evaluate(book)
        decision = personal(result)
        book["histories"].reverse()
        for history in book["histories"]:
            for resident in history["residents"]:
                resident["source"] = {"sheet": "Renamed", "row": 99}
                for posting in resident["postings"]:
                    posting["source"] = {"sheet": "Renamed", "row": 99, "column": "Z"}
        book["postings"]["electives"].reverse()
        for row in book["postings"]["electives"]:
            row["source"]["row"] += 100
        original = deepcopy(book)
        restored = evaluate(book, [decision])
        self.assertEqual(restored["entries"][0]["review"]["status"], "reviewed")
        self.assertEqual(restored["entries"][0]["review"]["requirement_year"], "R2")
        self.assertEqual(restored["entries"][0]["recorded_year"], "R3")
        self.assertEqual(book, original)

    def test_shared_alias_requires_explicit_data_and_never_assigns_resident_year(self):
        book = workbook()
        result = evaluate(book)
        self.assertTrue(all(e["match"]["status"] == "unmatched" for e in result["entries"]))
        result = evaluate(book, [alias(result)])
        self.assertTrue(all(e["review"]["status"] == "label_confirmed" for e in result["entries"]))
        self.assertTrue(all(e["review"]["requirement_year"] is None for e in result["entries"]))
        self.assertTrue(all(e["recorded_year"] == "R3" for e in result["entries"]))
        book["histories"][0]["residents"][0]["residency_year"] = "R2"
        changed = evaluate(book, [alias(result)])
        self.assertEqual(changed["entries"][0]["review"]["status"], "unreviewed")

    def test_changed_year_identity_period_label_or_target_are_unapplied_and_visible(self):
        for change, expected in (("year", "recorded_context_changed"), ("name", "recorded_context_changed"),
                                 ("period", "recorded_period_changed"), ("label", "recorded_period_changed"),
                                 ("target", "catalogue_target_changed_or_missing"),
                                 ("remarks", "catalogue_target_changed_or_missing")):
            with self.subTest(change=change):
                book = workbook()
                decision = personal(evaluate(book))
                if change in {"year", "name"}:
                    for history in book["histories"]:
                        history["residents"][0]["residency_year" if change == "year" else "name"] = "R4" if change == "year" else "Changed Example"
                elif change == "period":
                    book["histories"][1]["residents"][0]["postings"][0]["month"] = "2025-10"
                elif change == "label":
                    book["histories"][0]["residents"][0]["postings"][0]["value"] = "Changed label"
                elif change == "target":
                    book["postings"]["electives"].pop(0)
                else:
                    book["postings"]["electives"][0]["remarks"] = [{"text": "New relevant note"}]
                result = evaluate(book, [decision])
                self.assertFalse(any(e["review"]["status"] == "reviewed" for e in result["entries"]))
                self.assertIn(expected, result["decisions"][0]["reasons"])

    def test_ordinary_fallback_resolves_earlier_elective_but_retains_later_alternative(self):
        for recorded in ("R3", "R3,R4"):
            with self.subTest(recorded=recorded):
                book = self.cross_year_workbook()
                resident = book["histories"][0]["residents"][0]
                resident["residency_year"] = recorded
                resident["postings"][0]["value"] = "SITE Ward ( eLeCtIvE )"
                later = deepcopy(book["postings"]["electives"][0])
                later.update(residency_year="R5", source={"sheet": "Reference", "row": 99, "column": "B"})
                book["postings"]["electives"].append(later)
                original = deepcopy(book)
                entry = evaluate(book)["entries"][0]
                self.assertEqual(entry["review"]["status"], "automatic_match")
                self.assertEqual(entry["review"]["target"]["residency_year"], "R2")
                self.assertEqual(entry["match"]["selected_candidate"]["year_context"], "earlier_fallback_year")
                self.assertIn("earlier_year_fallback", entry["match"]["reasons"])
                self.assertEqual({c["residency_year"] for c in entry["match"]["candidates"]}, {"R2", "R5"})
                self.assertEqual(entry["recorded_year"], recorded)
                self.assertIsNone(entry["review"]["requirement_year"])
                self.assertEqual(book, original)

    def test_ordinary_fallback_never_bypasses_current_context_or_chooses_higher_years(self):
        for scenario in ("current", "current_ambiguous", "higher_only", "earlier_ambiguous"):
            with self.subTest(scenario=scenario):
                book = self.cross_year_workbook()
                resident = book["histories"][0]["residents"][0]
                resident["residency_year"] = "R3"
                if scenario in {"current", "current_ambiguous"}:
                    current = deepcopy(book["postings"]["core"][0])
                    current.update(residency_year="R3", source={"sheet": "Reference", "row": 98})
                    book["postings"]["core"].append(current)
                    if scenario == "current_ambiguous":
                        duplicate = deepcopy(current)
                        duplicate["source"]["row"] = 99
                        book["postings"]["core"].append(duplicate)
                elif scenario == "higher_only":
                    book["postings"]["core"][0]["residency_year"] = "R4"
                    book["postings"]["electives"][0]["residency_year"] = "R5"
                else:
                    another = deepcopy(book["postings"]["core"][0])
                    another.update(residency_year="R2", source={"sheet": "Reference", "row": 99})
                    book["postings"]["core"].append(another)
                entry = evaluate(book)["entries"][0]
                if scenario == "current":
                    self.assertEqual(entry["review"]["status"], "automatic_match")
                    self.assertEqual(entry["review"]["target"]["residency_year"], "R3")
                    self.assertNotIn("earlier_year_fallback", entry["match"]["reasons"])
                else:
                    self.assertIsNone(entry["match"]["selected_candidate"])
                    self.assertNotEqual(entry["review"]["status"], "automatic_match")
                    self.assertNotIn("earlier_year_fallback", entry["match"]["reasons"])

    def test_ordinary_fallback_applies_core_precedence_markers_and_saved_safety(self):
        book = self.cross_year_workbook()
        resident = book["histories"][0]["residents"][0]
        resident["residency_year"] = "R3"
        entry = evaluate(book)["entries"][0]
        self.assertEqual(entry["review"]["target"]["category"], "core")
        self.assertEqual(entry["review"]["target"]["residency_year"], "R1")
        self.assertEqual(len(entry["match"]["candidates"]), 3)
        resident["postings"][0]["value"] += " (Elective)"
        initial = evaluate(book)
        self.assertEqual(initial["entries"][0]["review"]["target"]["residency_year"], "R2")
        self.assertEqual(initial["entries"][0]["review"]["target"]["category"], "elective")
        decision = personal(initial, year="R2", candidate=4)
        conflict = evaluate(book, [decision, decision])["entries"][0]
        self.assertEqual(conflict["review"]["status"], "needs_review")
        self.assertIn("conflicting_saved_decisions", conflict["review"]["reasons"])
        book["postings"]["electives"][0]["remarks"] = [{"text": "Changed condition"}]
        stale = evaluate(book, [decision])["entries"][0]
        self.assertEqual(stale["review"]["status"], "needs_review")
        self.assertIn("catalogue_target_changed_or_missing", stale["review"]["reasons"])
        self.assertIsNone(stale["review"]["target"])

    def test_remediation_uses_all_earlier_years_and_keeps_recognized_labels_in_credit_review(self):
        for recorded, marker, expected_year, expected_category in (
                ("R3", "", "R1", "core"),
                ("R3", " (Elective)", "R2", "elective"),
                ("R2,R3", " ( eLeCtIvE ) ", "R2", "elective")):
            with self.subTest(recorded=recorded, marker=marker):
                book = self.cross_year_workbook()
                resident = book["histories"][0]["residents"][0]
                resident["residency_year"] = recorded
                resident["postings"][0]["value"] = "SITE Ward" + marker + " (Remediation)"
                original = deepcopy(book)
                result = evaluate(book)
                entry = result["entries"][0]
                self.assertEqual(entry["match"]["status"], "matched")
                self.assertEqual(entry["match"]["selected_candidate"]["year_context"], "earlier_remediation_year")
                self.assertEqual(entry["review"]["status"], "credit_review_required")
                self.assertEqual(entry["review"]["target"]["residency_year"], expected_year)
                self.assertEqual(entry["review"]["target"]["category"], expected_category)
                self.assertIsNone(entry["review"]["requirement_year"])
                self.assertIn("remediation_credit_review", entry["review"]["reasons"])
                self.assertEqual(entry["recorded_year"], recorded)
                self.assertNotIn("mixed_recorded_years", entry["match"]["reasons"])
                if not marker:
                    self.assertEqual(len(entry["match"]["candidates"]), 3)
                    future = next(c for c in entry["match"]["candidates"] if c["residency_year"] == "R4")
                    self.assertEqual(future["year_context"], "different_year")
                self.assertEqual(result["decisions"], [])
                self.assertEqual(book, original)

    def test_remediation_does_not_choose_immediate_prior_year_over_other_eligible_matches(self):
        for category in ("core", "elective"):
            with self.subTest(category=category):
                book = self.cross_year_workbook()
                resident = book["histories"][0]["residents"][0]
                resident["residency_year"] = "R3"
                resident["postings"][0]["value"] += " (Remediation)" + (" (Elective)" if category == "elective" else "")
                if category == "core":
                    another = deepcopy(book["postings"]["core"][0])
                    another.update(residency_year="R2", source={"sheet": "Reference", "row": 99})
                    book["postings"]["core"].append(another)
                else:
                    another = deepcopy(book["postings"]["electives"][0])
                    another.update(residency_year="R1", source={"sheet": "Reference", "row": 99, "column": "B"})
                    book["postings"]["electives"].append(another)
                entry = evaluate(book)["entries"][0]
                self.assertEqual(entry["match"]["status"], "ambiguous")
                self.assertIsNone(entry["match"]["selected_candidate"])
                self.assertIsNone(entry["review"]["target"])
                self.assertIn("remediation_credit_review", entry["review"]["reasons"])

    def test_remediation_requires_known_earlier_context_and_never_selects_current_or_future(self):
        for recorded, reason in (("R1", "no_earlier_year_context"), (None, "recorded_year_unknown"),
                                 ("Unknown", "recorded_year_unknown"), ("R2", "requirement_year_review")):
            with self.subTest(recorded=recorded):
                book = self.cross_year_workbook()
                resident = book["histories"][0]["residents"][0]
                resident["residency_year"] = recorded
                resident["postings"][0]["value"] += " (Remediation)"
                book["postings"]["core"][0]["residency_year"] = "R2"
                entry = evaluate(book)["entries"][0]
                self.assertIsNone(entry["match"]["selected_candidate"])
                self.assertIsNone(entry["review"]["target"])
                self.assertEqual(len(entry["match"]["candidates"]), 3)
                self.assertIn(reason, entry["match"]["reasons"])
                self.assertIn("remediation_credit_review", entry["review"]["reasons"])
        book = self.cross_year_workbook()
        resident = book["histories"][0]["residents"][0]
        resident["residency_year"] = "R3"
        resident["postings"][0]["value"] = "Unknown wording (Remediation)"
        self.assertIn("no_catalogue_match", evaluate(book)["entries"][0]["match"]["reasons"])

    def test_remediation_recognition_does_not_override_saved_decisions_or_catalogue_safety(self):
        for scenario in ("stale", "conflict", "valid", "unknown_catalogue", "mixed_catalogue"):
            with self.subTest(scenario=scenario):
                book = self.cross_year_workbook()
                resident = book["histories"][0]["residents"][0]
                resident["residency_year"] = "R3"
                resident["postings"][0]["value"] += " (Remediation)"
                initial = evaluate(book)
                decisions = []
                if scenario in {"unknown_catalogue", "mixed_catalogue"}:
                    book["postings"]["core"][0]["residency_year"] = None if scenario == "unknown_catalogue" else "R1,R2"
                else:
                    # A reviewed elective decision takes precedence over inferred core wording.
                    decision = personal(initial, year="R2", candidate=4)
                    decisions = [decision, decision] if scenario == "conflict" else [decision]
                    if scenario == "stale":
                        book["postings"]["electives"][0]["remarks"] = [{"text": "Changed condition"}]
                entry = evaluate(book, decisions)["entries"][0]
                self.assertIn("remediation_credit_review", entry["review"]["reasons"])
                if scenario == "valid":
                    self.assertEqual(entry["review"]["status"], "credit_review_required")
                    self.assertEqual(entry["review"]["target"]["category"], "elective")
                    self.assertEqual(entry["review"]["requirement_year"], "R2")
                else:
                    self.assertIsNone(entry["review"]["target"])
                    self.assertEqual(entry["review"]["status"], "needs_review" if decisions else "unreviewed")
                if scenario == "conflict":
                    self.assertIn("conflicting_saved_decisions", entry["review"]["reasons"])
                if scenario == "stale":
                    self.assertIn("catalogue_target_changed_or_missing", entry["review"]["reasons"])

    def test_remediation_qualifier_and_credit_review_survive_confirmation(self):
        book = workbook()
        book["histories"][0]["residents"][0]["postings"][0]["value"] += " (Remediation)"
        initial = evaluate(book)
        result = evaluate(book, [personal(initial)])
        entry = result["entries"][0]
        self.assertIn("(Remediation)", entry["months"][0]["value"])
        self.assertEqual(entry["review"]["status"], "credit_review_required")
        self.assertIn("remediation_credit_review", entry["review"]["reasons"])

    def test_unrecognized_remediation_qualifier_keeps_credit_warning_after_manual_review(self):
        book = workbook()
        book["histories"][0]["residents"][0]["postings"][0]["value"] += " (Remediation R2)"
        initial = evaluate(book)
        self.assertEqual(initial["entries"][0]["match"]["status"], "unmatched")
        result = evaluate(book, [personal(initial)])
        entry = result["entries"][0]
        self.assertEqual(entry["review"]["status"], "credit_review_required")
        self.assertIn("(Remediation R2)", entry["months"][0]["value"])
        self.assertIn("remediation_credit_review", entry["review"]["reasons"])

    def test_identity_conflicts_block_resident_decisions_but_not_wording_aliases(self):
        book = workbook()
        book["histories"] = book["histories"][:1]
        initial = evaluate(book)
        decision = personal(initial)
        book["issues"] = [{"code": "conflicting_identity", "records": [{"source": book["histories"][0]["residents"][0]["source"]}]}]
        result = evaluate(book, [decision])
        self.assertFalse(result["entries"][0]["identity_safe"])
        self.assertIn("identity_review_required", result["entries"][0]["review"]["reasons"])
        duplicate = deepcopy(book["histories"][0]["residents"][0])
        duplicate["source"]["row"] = 44
        duplicate["match_status"] = "ambiguous"
        book["histories"][0]["residents"].append(duplicate)
        entries = evaluate(book)["entries"]
        self.assertEqual(entries[0]["key"], entries[1]["key"])
        self.assertNotEqual(entries[0]["id"], entries[1]["id"])

    def test_conflicts_do_not_poison_unrelated_entries_or_depend_on_order(self):
        book = workbook()
        first = book["histories"][0]["residents"][0]
        for i in (2, 3):
            person = deepcopy(first)
            person.update(mcr=f"M00{i}", name=f"Example {i}")
            person["source"]["row"] = i + 10
            book["histories"][0]["residents"].append(person)
        initial = evaluate(book)
        # Deliberately conflict only for M002; the shared alias still applies elsewhere.
        conflicting = next(i for i, entry in enumerate(initial["entries"]) if entry["mcr"] == "M002")
        decisions = [alias(initial), personal(initial, index=conflicting, year="R5", candidate=2)]
        expected = None
        for order in permutations(book["histories"][0]["residents"]):
            book["histories"][0]["residents"] = list(order)
            result = evaluate(book, decisions)
            actual = sorted((e["context"]["mcr"], e["key"], e["review"]["status"]) for e in result["entries"])
            if expected is None:
                expected = actual
            self.assertEqual(actual, expected)
            self.assertTrue(all(e["review"]["status"] == "label_confirmed" for e in result["entries"] if e["context"]["mcr"] != "M002"))
            self.assertEqual(next(e for e in result["entries"] if e["context"]["mcr"] == "M002")["review"]["status"], "needs_review")

    def test_incompatible_year_core_target_and_duplicate_decisions_stay_unapplied(self):
        book = workbook()
        initial = evaluate(book)
        for decision, reason in ((personal(initial, year="R5"), "incompatible_requirement_year"),
                                 (personal(initial, candidate=0), "explicit_elective_target_required")):
            result = evaluate(book, [decision])
            self.assertEqual(result["entries"][0]["review"]["status"], "needs_review")
            self.assertIn(reason, result["entries"][0]["review"]["reasons"])
        result = evaluate(book, [personal(initial), personal(initial)])
        self.assertIn("conflicting_saved_decisions", result["entries"][0]["review"]["reasons"])

    def test_api_validation_and_serialization_are_actionable(self):
        with TestClient(app) as client:
            valid = {"workbook": workbook(), "store": {"version": 1, "decisions": []}}
            response = client.post('/api/history-review', json=valid)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(response.json()["entries"][0]["months"]), 3)
            for payload in ({}, {**valid, "store": {"version": 2, "decisions": []}},
                            {**valid, "workbook": {"postings": {"core": [None]}}}):
                self.assertEqual(client.post('/api/history-review', json=payload).status_code, 422)
        with self.assertRaises(ValidationError):
            decision = alias(evaluate(workbook()))
            decision["requirement_year"] = "R2"
            ReviewStore.model_validate({"version": 1, "decisions": [decision]})


def timetable_workbook(value=" site  department "):
    book = workbook()
    resident = deepcopy(book["histories"][0]["residents"][0])
    resident["source"] = {"sheet": "Current timetable", "row": 12}
    resident["postings"] = [{"month": month, "value": value, "status": "posting",
                              "source": {"sheet": "Current timetable", "row": 12, "column": column}}
                             for month, column in (("2027-07", "G"), ("2027-08", "H"))]
    book["residents"] = [resident]
    return book


class TimetableLabelReviewTests(unittest.TestCase):
    def evaluate(self, book, decisions=None):
        return evaluate_review(book, ReviewStore.model_validate({"version": 1, "decisions": decisions or []}), "timetable")

    def test_timetable_scope_resolves_target_year_without_changing_history_default_or_records(self):
        book = timetable_workbook()
        original = deepcopy(book)
        current = self.evaluate(book)
        self.assertEqual(len(current["entries"]), 1)
        self.assertEqual([m["month"] for m in current["entries"][0]["months"]], ["2027-07", "2027-08"])
        self.assertEqual(current["entries"][0]["review"]["status"], "automatic_match")
        self.assertEqual(current["entries"][0]["review"]["target"]["label"], "SITE Department")
        self.assertTrue(all(m["month"].startswith("2025-") for e in evaluate(book)["entries"] for m in e["months"]))
        self.assertEqual(book, original)

    def test_valid_target_resident_decision_and_shared_mapping_precede_automatic_match(self):
        book = timetable_workbook()
        initial = self.evaluate(book)
        self.assertEqual(initial["entries"][0]["review"]["target"]["category"], "core")
        personal_decision = personal(initial, year="R2", candidate=1)
        manual = self.evaluate(book, [personal_decision])["entries"][0]
        self.assertEqual(manual["review"]["status"], "reviewed")
        self.assertEqual(manual["review"]["target"]["category"], "elective")
        shared = alias(initial)
        shared["context"]["label"] = initial["entries"][0]["months"][0]["value"]
        mapped = self.evaluate(book, [shared])["entries"][0]
        self.assertEqual(mapped["review"]["status"], "label_confirmed")
        self.assertEqual(mapped["review"]["target"]["category"], "elective")
        # Changes in catalogue source positions alone preserve manual target identity.
        book["postings"]["electives"][0]["source"]["row"] += 40
        self.assertEqual(self.evaluate(book, [personal_decision])["entries"][0]["review"]["target"]["category"], "elective")

    def test_timetable_stale_conflicting_and_unsafe_personal_decisions_remain_unapplied(self):
        for scenario in ("stale", "conflict", "identity"):
            with self.subTest(scenario=scenario):
                book = timetable_workbook()
                decision = personal(self.evaluate(book), year="R2", candidate=1)
                decisions = [decision, decision] if scenario == "conflict" else [decision]
                if scenario == "stale":
                    book["postings"]["electives"][0]["remarks"] = [{"text": "Changed condition"}]
                elif scenario == "identity":
                    book["issues"] = [{"code": "conflicting_identity", "records": [{"source": book["residents"][0]["source"]}]}]
                result = self.evaluate(book, decisions)
                self.assertEqual(result["entries"][0]["review"]["status"], "needs_review")
                self.assertIsNone(result["entries"][0]["review"]["target"])
                self.assertEqual(result["decisions"][0]["status"], "needs_review")

    def test_overlapping_changed_or_cross_year_personal_period_never_broadens_into_target(self):
        for scenario in ("partial", "cross_year", "changed_label"):
            with self.subTest(scenario=scenario):
                book = timetable_workbook()
                decision = personal(self.evaluate(book), year="R2", candidate=1)
                if scenario == "partial":
                    decision["context"]["months"] = decision["context"]["months"][:1]
                elif scenario == "cross_year":
                    decision["context"]["months"][0]["month"] = "2027-06"
                else:
                    decision["context"]["months"][0]["value"] = "Different prior label"
                entry = self.evaluate(book, [decision])["entries"][0]
                self.assertEqual(entry["review"]["status"], "needs_review")
                self.assertIsNone(entry["review"]["target"])
                self.assertIn("recorded_period_changed", entry["review"]["reasons"])

    def test_nonoverlapping_or_other_resident_decisions_do_not_block_safe_target_matching(self):
        book = timetable_workbook()
        initial = self.evaluate(book)
        prior = personal(initial, year="R2", candidate=1)
        for month in prior["context"]["months"]:
            month["month"] = month["month"].replace("2027", "2026")
        other = personal(initial, year="R2", candidate=1)
        other["context"]["mcr"] = "M999"
        result = self.evaluate(book, [prior, other])
        self.assertEqual(result["entries"][0]["review"]["status"], "automatic_match")
        self.assertTrue(all(state["status"] == "not_present" for state in result["decisions"]))

    def test_timetable_scope_is_validated_and_omitted_scope_still_reviews_only_history(self):
        with TestClient(app) as client:
            payload = {"workbook": timetable_workbook(), "store": {"version": 1, "decisions": []}}
            history = client.post('/api/history-review', json=payload)
            current = client.post('/api/history-review', json={**payload, "scope": "timetable"})
            self.assertEqual(history.status_code, 200, history.text)
            self.assertEqual(current.status_code, 200, current.text)
            self.assertTrue(history.json()["entries"][0]["months"][0]["month"].startswith("2025-"))
            self.assertEqual(current.json()["entries"][0]["months"][0]["month"], "2027-07")
            self.assertEqual(client.post('/api/history-review', json={**payload, "scope": "all"}).status_code, 422)


def all_year_workbook_bytes(duplicate_target=False):
    def edit(w):
        for title in ("Jul 2026 - Jun 2027", "Jul 2027 - Jun 2028"):
            sheet = w[title]
            for merged in list(sheet.merged_cells.ranges):
                sheet.unmerge_cells(str(merged))
            start, row = (2, 4) if title.startswith("Jul 2026") else (4, 3)
            for column, value in enumerate(("Main Example", "M001", "R3"), start):
                sheet.cell(row, column, value)
            for column in range(start + 3, start + 15):
                sheet.cell(row, column, "SITE Department")
        future = w.copy_worksheet(w["Jul 2027 - Jun 2028"])
        future.title = "Jul 2028 - Jun 2029"
        for cell in future[1]:
            if hasattr(cell.value, "year"):
                cell.value = cell.value.replace(year=cell.value.year + 1)
        for sheet, start, row in ((w["Jul 2026 - Jun 2027"], 2, 5), (future, 4, 4)):
            for column, value in enumerate(("Jamie Example", "M002", "R3"), start):
                sheet.cell(row, column, value)
            for column in range(start + 3, start + 15):
                sheet.cell(row, column, "Unknown shared wording")
        future["D5"], future["F5"] = "Missing identifier", "R1"
        if duplicate_target:
            current = w["Jul 2027 - Jun 2028"]
            for column in range(4, 19):
                current.cell(4, column, current.cell(3, column).value)
        request = w["Request"]
        for column, value in enumerate(("Jamie Example", "M002", "R3", "Original request", "Any suitable month"), 1):
            request.cell(2, column, value)
        request.append(["Unknown Example", "M999", "R2", "Second request", "Unqualified period"])
        w["Postings"]["D2"], w["Postings"]["E2"] = "R2", "SITE Department"
    return workbook_bytes(edit)


class AllYearReviewTests(unittest.TestCase):
    def test_all_annual_data_review_keys_queue_and_issues_are_independent_of_planning_year(self):
        content = all_year_workbook_bytes()
        imported = [parse_workbook(content, year) for year in (2026, 2027, 2028)]
        baseline = None
        for year, book in zip((2026, 2027, 2028), imported):
            self.assertEqual([sheet["year"] for sheet in book["annual_sheets"]], [2026, 2027, 2028])
            self.assertEqual(sum(sheet["year"] == year for sheet in book["annual_sheets"]), 1)
            self.assertEqual([sheet["year"] for sheet in book["histories"]], list(range(2026, year)))
            result = evaluate(book)
            main = next(entry for entry in result["entries"] if entry["mcr"] == "M001")
            self.assertEqual(len(main["months"]), 36)
            self.assertEqual(len({month["month"] for month in main["months"]}), 36)
            self.assertEqual(main["months"][0]["month"], "2026-07")
            self.assertEqual(main["months"][-1]["month"], "2029-06")
            # Planning-intake warnings follow the selected year; shared identity
            # and history review remain independent of that selection.
            shared_issues = [issue for issue in book["issues"] if issue["code"] not in {"unclear_intake", "excess_intake", "intake_fill_blocked"}]
            state = ([(entry["key"], entry["review"], entry["identity_safe"]) for entry in result["entries"]], shared_issues)
            if baseline is None:
                baseline = state
            self.assertEqual(state, baseline)
            self.assertIn("missing_mcr", [issue["code"] for issue in book["issues"]])
            target = evaluate_review(book, ReviewStore(version=1, decisions=[]), "timetable")
            self.assertTrue(all(month["month"] >= f"{year}-07" and month["month"] <= f"{year + 1}-06"
                                for entry in target["entries"] for month in entry["months"]))

    def test_request_rows_are_unqualified_and_unchanged_while_selected_resident_links_change(self):
        content = all_year_workbook_bytes()
        raw = None
        for year, expected in ((2026, "matched"), (2027, "unmatched"), (2028, "matched")):
            book = parse_workbook(content, year)
            records = [{key: value for key, value in request.items() if key not in {"match_status", "matched_resident_source"}}
                       for request in book["requests"]]
            if raw is None:
                raw = records
            self.assertEqual(records, raw)
            self.assertEqual(len(records), 2)
            self.assertEqual(book["requests"][0]["match_status"], expected)
            self.assertEqual(book["requests"][0]["period"], "Any suitable month")
            if expected == "matched":
                self.assertEqual(book["requests"][0]["matched_resident_source"]["sheet"], book["target_sheet"])
            else:
                self.assertIsNone(book["requests"][0]["matched_resident_source"])
            unmatched = next(issue for issue in book["issues"] if issue["code"] == "unmatched_request")
            self.assertEqual([record["mcr"] for record in unmatched["records"]], ["M999"])

    def test_global_identity_sources_keep_grouping_stable_when_selected_link_is_ambiguous(self):
        content = all_year_workbook_bytes(duplicate_target=True)
        baseline = None
        for year in (2026, 2027, 2028):
            book = parse_workbook(content, year)
            past = book["annual_sheets"][0]["residents"][0]
            self.assertEqual(past["match_status"], "ambiguous" if year == 2027 else "matched")
            result = evaluate(book)
            state = [(entry["key"], entry["identity_safe"]) for entry in result["entries"]]
            if baseline is None:
                baseline = state
            self.assertEqual(state, baseline)
            earlier = next(entry for entry in result["entries"] if entry["mcr"] == "M001" and entry["months"][0]["month"] == "2026-07")
            self.assertTrue(earlier["identity_safe"])
            duplicated = [entry for entry in result["entries"] if entry["mcr"] == "M001" and entry["months"][0]["month"] == "2027-07"]
            self.assertEqual(len(duplicated), 2)
            self.assertTrue(all(not entry["identity_safe"] for entry in duplicated))

    def test_old_cutoff_period_decision_is_visible_unapplied_without_broadening_to_full_run(self):
        book = parse_workbook(all_year_workbook_bytes(), 2027)
        legacy = deepcopy(book)
        legacy.pop("annual_sheets")
        old = evaluate(legacy)
        index = next(index for index, entry in enumerate(old["entries"]) if entry["mcr"] == "M001")
        decision = personal(old, index=index, year="R2", candidate=0)
        original_decision = deepcopy(decision)
        result = evaluate(book, [decision])
        main = next(entry for entry in result["entries"] if entry["mcr"] == "M001")
        self.assertEqual(len(decision["context"]["months"]), 12)
        self.assertEqual(len(main["months"]), 36)
        self.assertEqual(main["review"]["status"], "needs_review")
        self.assertIn("recorded_period_changed", main["review"]["reasons"])
        self.assertIsNone(main["review"]["target"])
        self.assertEqual(result["decisions"][0]["status"], "needs_review")
        self.assertEqual(decision, original_decision)


if __name__ == '__main__':
    unittest.main()
