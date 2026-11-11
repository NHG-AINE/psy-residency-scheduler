"""Conjunction spelling is matching-only; catalogue/source labels stay intact."""
import unittest
from copy import deepcopy

from programme_requirements import validate_posting
from request_preferences import resolve_requests
from workbook_import import match_posting, posting_catalogue, normalized_label


class PostingConjunctionTests(unittest.TestCase):
    def test_core_history_validation_and_requests_keep_catalogue_wording(self):
        for year, service in (("R1", "Medicine & Neurology"),
                              ("R2", "Child & Adolescent Psychiatry"),
                              ("R5", "Child & Adolescent Psychiatry")):
            for catalogue_and in (True, False):
                with self.subTest(year=year, catalogue_and=catalogue_and):
                    catalogue_service = service.replace("&", "and") if catalogue_and else service
                    history_service = service if catalogue_and else service.replace("&", "AND")
                    label = "NUH " + catalogue_service
                    rows = [{"residency_year": year, "posting": label,
                             "source": {"sheet": "Postings", "row": 48}}]
                    catalogue = posting_catalogue({"core": rows})
                    history = {"status": "posting", "value": "NUH " + history_service}
                    original = deepcopy((rows, history))
                    matched = match_posting(history, year, catalogue)
                    self.assertEqual(matched["status"], "matched")
                    target = matched["selected_candidate"]
                    self.assertEqual(target["label"], label)
                    validated = validate_posting(year, target, core_catalogue=rows)
                    self.assertTrue(validated["valid"], validated)
                    self.assertEqual((rows, history), original)
                    if year == "R1":
                        continue  # Requests apply from R2 onwards.
                    source = {"sheet": "AY", "row": 2}
                    person = {"source": source, "recorded_years": [year.lower()], "requirements": [{
                        "requirement_id": validated["requirement_id"], "requirement_year": year,
                        "required_months": 3, "remaining_months": 3}]}
                    option = {**target, **validated}
                    for text in (history_service, "NUH " + history_service):
                        request = {"matched_resident_source": source, "posting_request": text, "period": None}
                        result = resolve_requests(person, [request], [option],
                                                  [{"month": f"2027-{m:02d}"} for m in (7, 8, 9)])[0]
                        self.assertEqual(result["status"], "evaluable")
                        self.assertEqual(result["option_keys"][0][2], label)
                        self.assertEqual(result["request"]["posting_request"], text)

    def test_elective_markers_and_combined_requirements_are_not_weakened(self):
        rows = [{"residency_year": "R5", "institution": "IMH",
                 "elective": "Child and Adolescent Psychiatry", "source": {"sheet": "Postings", "row": 12}}]
        catalogue = posting_catalogue({"electives": rows})
        matched = match_posting({"status": "posting", "value": "IMH Child & Adolescent Psychiatry (Elective)"}, "R5", catalogue)
        self.assertEqual(matched["status"], "matched")
        self.assertEqual(matched["selected_candidate"]["category"], "elective")
        target = dict(catalogue[0], label="IMH Child & Adolescent Psychiatry")
        self.assertTrue(validate_posting("R5", target, rows)["valid"])
        combined = {"residency_year": "R5", "category": "core", "label": "IMH Child and Geriatric Psychiatry"}
        self.assertEqual(validate_posting("R5", combined, core_catalogue=[{
            "residency_year": "R5", "posting": combined["label"]}])["reasons"], ["posting_not_required_for_year"])
        self.assertNotEqual(normalized_label("A & B"), normalized_label("A and B"))


if __name__ == "__main__":
    unittest.main()
