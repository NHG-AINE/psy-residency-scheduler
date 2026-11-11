"""Regional annotations affect matching only, never source labels or categories."""
import unittest
from copy import deepcopy

from programme_requirements import validate_posting
from request_preferences import resolve_requests
from workbook_import import match_posting, normalized_posting_label, posting_catalogue


class PostingRegionTests(unittest.TestCase):
    def test_regions_on_either_side_match_history_validation_and_requests(self):
        for region in ("North", "sOuTh", "EAST", "west"):
            for category in ("core", "elective"):
                for annotated_catalogue in (False, True):
                    with self.subTest(region=region, category=category, catalogue=annotated_catalogue):
                        service = "Geriatric Psychiatry" if category == "core" else "ANDS"
                        annotated = service + f" ( {region} )"
                        catalogue_service = annotated if annotated_catalogue else service
                        input_service = service if annotated_catalogue else annotated
                        label = "IMH " + catalogue_service
                        row = {"residency_year": "R2", "source": {"sheet": "Postings", "row": 4}}
                        if category == "core":
                            row["posting"] = label
                        else:
                            row.update(institution="IMH", elective=catalogue_service)
                        rows = [row]
                        catalogue = posting_catalogue({"core" if category == "core" else "electives": rows})
                        marker = " (Elective)" if category == "elective" else ""
                        history = {"status": "posting", "value": "IMH " + input_service + marker}
                        original = deepcopy((rows, history, catalogue))
                        match = match_posting(history, "R2", catalogue)
                        self.assertEqual(match["status"], "matched")
                        target = match["selected_candidate"]
                        self.assertEqual(target["label"], label)
                        # Check both programme-name recognition and catalogue membership
                        # with the regional annotation on opposite sides.
                        alternate = dict(target, label="IMH " + input_service)
                        for candidate in (target, alternate):
                            validated = validate_posting("R2", candidate, rows if category == "elective" else (),
                                                         core_catalogue=rows if category == "core" else ())
                            self.assertTrue(validated["valid"], validated)
                        option = {**target, **validate_posting("R2", target, rows if category == "elective" else (),
                                                             core_catalogue=rows if category == "core" else ())}
                        source = {"sheet": "AY", "row": 2}
                        person = {"source": source, "recorded_years": ["r2"], "requirements": [{
                            "requirement_id": option["requirement_id"], "requirement_year": "R2",
                            "required_months": 3, "remaining_months": 3}]}
                        for requested in (input_service, "IMH " + input_service):
                            request = {"matched_resident_source": source, "posting_request": requested + marker}
                            outcome = resolve_requests(person, [request], [option], [{"month": "2027-07"}])[0]
                            self.assertEqual(outcome["status"], "evaluable")
                            self.assertEqual(outcome["option_keys"], [(option["requirement_id"], "IMH", label)])
                            self.assertEqual(outcome["request"], request)
                        self.assertEqual((rows, history, catalogue), original)

    def test_only_standalone_regional_parentheses_are_ignored(self):
        self.assertEqual(normalized_posting_label("A & B (North)"), normalized_posting_label("A and B"))
        for suffix in ("(Elective)", "(Remediation)", "(Unknown)", "(North East)", "(Northern)", "North"):
            with self.subTest(suffix=suffix):
                self.assertNotEqual(normalized_posting_label("ANDS " + suffix), normalized_posting_label("ANDS"))
        self.assertEqual(normalized_posting_label("ANDS (West)"), "ands")
        self.assertEqual(normalized_posting_label("Adult Neurodevelopmental Disorders Service (ANDS) (East)"),
                         "adult neurodevelopmental disorders service (ands)")
        catalogue = posting_catalogue({"core": [{"residency_year": "R2", "posting": "IMH Geriatric Psychiatry",
                                                "source": {"sheet": "Postings", "row": 4}}]})
        for suffix, status in (("(North) (Unknown)", "unmatched"), ("(North) (Elective)", "unmatched"),
                               ("(North) (Remediation)", "matched")):
            with self.subTest(suffix=suffix):
                result = match_posting({"status": "posting", "value": "IMH Geriatric Psychiatry " + suffix},
                                       "R3" if "Remediation" in suffix else "R2", catalogue)
                self.assertEqual(result["status"], status)
                if "Remediation" in suffix:
                    self.assertIn("remediation_credit_review", result["reasons"])


if __name__ == "__main__":
    unittest.main()
