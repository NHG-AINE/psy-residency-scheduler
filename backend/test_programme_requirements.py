"""Programme eligibility and declarative R3 continuity, without ledger accounting."""
import unittest
from copy import deepcopy

from programme_requirements import PROGRAMME_REQUIREMENTS, R1_COMPLETION_ROUTES, validate_posting


def target(year, label, category="core"):
    return {"residency_year": year, "label": label, "category": category,
            "source": {"sheet": "Synthetic catalogue", "row": 41}, "duration_months": "99"}


class ProgrammeRequirementsTests(unittest.TestCase):
    def test_programme_durations_override_workbook_values_and_requirements_stay_year_specific(self):
        cases = (("R1", "TTSH General Medicine", 4), ("R1", "NNI Neurology", 2),
                 ("R1", "NUH Medicine & Neurology", 6), ("R1", "IMH Inpatient Psychiatry", 6),
                 ("R2", "SGH Geriatric Psychiatry", 3), ("R2", "IMH Addiction Medicine", 3),
                 ("R4", "IMH Inpatient Psychiatry", 3), ("R5", "KKH Child & Adolescent Psychiatry", 3))
        for year, label, months in cases:
            with self.subTest(year=year, label=label):
                result = validate_posting(year, target(year, label))
                self.assertTrue(result["valid"], result)
                self.assertEqual(result["required_months"], months)
                self.assertTrue(result["requirement_id"].startswith(year.lower() + "."))
        self.assertNotEqual(validate_posting("R1", target("R1", "IMH Inpatient Psychiatry"))["requirement_id"],
                            validate_posting("R4", target("R4", "IMH Inpatient Psychiatry"))["requirement_id"])

        r1 = {row["id"]: row for row in PROGRAMME_REQUIREMENTS["R1"].values()}
        self.assertEqual(R1_COMPLETION_ROUTES, (
            ("r1.general_medicine", "r1.neurology", "r1.inpatient_psychiatry"),
            ("r1.medicine_neurology", "r1.inpatient_psychiatry"),
        ))
        for route in R1_COMPLETION_ROUTES:
            self.assertEqual(sum(r1[key]["months"] for key in route), 12)
        for label in ("TTSH General Medicine", "NNI Neurology", "NUH Medicine & Neurology"):
            self.assertEqual(validate_posting("R1", target("R1", label))["training_months"], (1, 6))
        self.assertEqual(validate_posting("R1", target("R1", "IMH Inpatient Psychiatry"))["training_months"], (7, 12))

    def test_validates_requirement_year_then_posting_then_institution_without_expanding_programme(self):
        cases = (("R9", target("R1", "IMH Inpatient Psychiatry"), "unknown_requirement_year"),
                 ("R2", target("R5", "IMH Geriatric Psychiatry"), "catalogue_year_mismatch"),
                 ("R2", target("R2,R3", "IMH Addiction Medicine"), "catalogue_year_not_specific"),
                 ("R2", None, "unresolved_catalogue_target"),
                 ("R1", target("R1", "KKH Child & Adolescent Psychiatry"), "posting_not_required_for_year"),
                 ("R2", target("R2", "TTSH Geriatric Psychiatry"), "institution_not_allowed"),
                 ("R4", target("R4", "IMH Consultation Liaison Psychiatry"), "institution_not_allowed"),
                 ("R1", target("R1", "SGH Medicine & Neurology"), "institution_not_allowed"),
                 ("R3", target("R3", "KKH Continuity Clinic"), "institution_not_allowed"),
                 ("R5", target("R5", "SGH Geriatric Psychiatry"), "institution_not_allowed"),
                 ("R3", target("R3", "IMH Continuity Clinic Research"), "posting_not_required_for_year"))
        for year, resolved, reason in cases:
            with self.subTest(year=year, resolved=resolved):
                result = validate_posting(year, resolved)
                self.assertFalse(result["valid"])
                self.assertEqual(result["reasons"], [reason])
                self.assertIsNone(result["progress_key"])
        rejected = validate_posting("R2", target("R2", "TTSH Geriatric Psychiatry"))
        self.assertEqual(rejected["requirement_id"], "r2.geriatric_psychiatry")
        self.assertEqual(rejected["required_months"], 3)

    def test_electives_require_exact_year_posting_and_institution_and_use_programme_duration(self):
        catalogue = [{"residency_year": year, "institution": "SITE", "elective": "Department"}
                     for year in ("R2", "R5")]
        for year, months in (("R2", 3), ("R5", 6)):
            result = validate_posting(year, target(year, " site  department ", "elective"), catalogue)
            self.assertTrue(result["valid"], result)
            self.assertEqual(result["required_months"], months)
            self.assertEqual(result["requirement_id"], year.lower() + ".elective")
        wrong_site = validate_posting("R2", target("R2", "OTHER Department", "elective"), catalogue)
        self.assertEqual(wrong_site["reasons"], ["institution_not_allowed"])
        wrong_name = validate_posting("R2", target("R2", "SITE Department Psychiatry", "elective"), catalogue)
        self.assertEqual(wrong_name["reasons"], ["elective_not_in_catalogue_for_year"])
        wrong_year = validate_posting("R2", target("R2", "SITE Department", "elective"), catalogue[1:])
        self.assertEqual(wrong_year["reasons"], ["elective_not_in_catalogue_for_year"])
        missing = validate_posting("R2", target("R2", "SITE Department", "elective"))
        self.assertEqual(missing["reasons"], ["elective_catalogue_missing"])
        unavailable = validate_posting("R3", target("R3", "SITE Department", "elective"), catalogue)
        self.assertEqual(unavailable["reasons"], ["posting_not_required_for_year"])

    def test_r3_is_one_twelve_month_clinic_requirement_with_separate_institution_progress(self):
        self.assertEqual(len(PROGRAMME_REQUIREMENTS["R3"]), 1)
        sites = ("IMH", "TTSH", "KTPH", "WH", "CGH", "SGH", "NUH", "NTFGH", "AH")
        results = [validate_posting("R3", target("R3", site + " Continuity Clinic")) for site in sites]
        self.assertTrue(all(result["valid"] for result in results))
        self.assertEqual({result["requirement_id"] for result in results}, {"r3.continuity_clinic"})
        self.assertTrue(all(result["required_months"] == 12 for result in results))
        self.assertEqual(len({result["progress_key"] for result in results}), 9)
        self.assertEqual(results[0]["continuity"], {"same_posting": True, "same_institution": True, "loa": "pause"})
        for posting in ("CMHT", "Community Mental Health Team (CMHT)", "CBT",
                        "Cognitive Behavioural Therapy (CBT)", "Psychodynamic Psychotherapy"):
            result = validate_posting("R3", target("R3", "IMH " + posting))
            self.assertFalse(result["valid"])
            self.assertEqual(result["reasons"], ["posting_not_required_for_year"])
            self.assertIsNone(result["progress_key"])

    def test_eligibility_does_not_confirm_year_credit_or_change_review_state(self):
        entry = {"recorded_year": "R3", "identity_safe": False,
                 "match": {"reasons": ["remediation_credit_review"]},
                 "review": {"status": "credit_review_required", "requirement_year": None,
                            "target": target("R2", "IMH Addiction Medicine")}}
        original = deepcopy(entry)
        result = validate_posting("R2", entry["review"]["target"])
        self.assertTrue(result["valid"])
        self.assertEqual(result["requirement_id"], "r2.addiction_medicine")
        self.assertEqual(entry, original)
        self.assertEqual(entry["recorded_year"], "R3")
        self.assertIsNone(entry["review"]["requirement_year"])
        self.assertNotIn("credited_months", result)
        self.assertNotIn("remaining_months", result)
        self.assertNotIn("completed", result)

    def test_validation_does_not_mutate_targets_catalogue_or_shared_programme_policy(self):
        resolved = target("R2", "SITE Department", "elective")
        catalogue = [{"residency_year": "R2", "institution": "SITE", "elective": "Department", "remarks": []}]
        before = deepcopy((resolved, catalogue, PROGRAMME_REQUIREMENTS))
        validate_posting("R2", resolved, catalogue)
        r3 = validate_posting("R3", target("R3", "IMH Continuity Clinic"))
        r3["continuity"]["loa"] = "changed externally"
        self.assertEqual((resolved, catalogue, PROGRAMME_REQUIREMENTS), before)


if __name__ == "__main__":
    unittest.main()
