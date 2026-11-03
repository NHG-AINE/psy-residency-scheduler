import unittest
from copy import deepcopy

from history_review import ReviewStore, evaluate_review
from requirement_ledger import build_requirement_ledger


def resident(months, year="R1", sheet="History", row=3):
    return {"name": "Alex Example", "mcr": "M001", "residency_year": year,
            "source": {"sheet": sheet, "row": row}, "match_status": "matched",
            "postings": [{"month": month, "value": value,
                          "status": "blank" if value is None else "loa" if value == "LOA" else "posting",
                          "source": {"sheet": sheet, "row": row, "column": str(i)}}
                         for i, (month, value) in enumerate(months)]}


def book(history, planning="2027-07"):
    roster = resident([], "R4", "Planning")
    labels = [("R1", "TTSH General Medicine"), ("R1", "NNI Neurology"),
              ("R1", "NUH Medicine & Neurology"), ("R1", "IMH Inpatient Psychiatry"),
              ("R3", "IMH Continuity Clinic"), ("R3", "TTSH Continuity Clinic"),
              ("R4", "IMH Emergency Psychiatry"), ("R2", "TTSH Geriatric Psychiatry")]
    return {"target_year": int(planning[:4]), "months": [{"month": planning}], "residents": [roster],
            "annual_sheets": [{"residents": history}, {"residents": [roster]}], "histories": [], "issues": [],
            "postings": {"core": [{"posting": label, "residency_year": year,
                                    "source": {"sheet": "Reference", "row": i}} for i, (year, label) in enumerate(labels)],
                         "electives": []}}


def ledger(workbook, decisions=()):
    return build_requirement_ledger(workbook, ReviewStore.model_validate({"version": 1, "decisions": list(decisions)}))


def requirement(result, key):
    return next(item for item in result["residents"][0]["requirements"] if item["requirement_id"] == key)


class RequirementLedgerTests(unittest.TestCase):
    def test_dynamic_cutoff_sources_duplicates_and_no_mutation(self):
        history = resident([("2026-06", "TTSH General Medicine"), ("2026-07", "TTSH General Medicine")])
        duplicate = deepcopy(history)
        duplicate["source"] = {"sheet": "Duplicate", "row": 8}
        for posting in duplicate["postings"]:
            posting["source"] = {**posting["source"], "sheet": "Duplicate"}
        workbook = book([history, duplicate], "2026-07")
        original = deepcopy(workbook)
        result = ledger(workbook)
        self.assertEqual(result["cutoff"], "2026-06")
        self.assertEqual(requirement(result, "r1.general_medicine")["expected_months"], 1)
        self.assertEqual(len(result["residents"][0]["months"][0]["evidence"]), 2)
        self.assertEqual(result["residents"][0]["recorded_year"], "R4")
        workbook["target_year"], workbook["months"] = 2027, [{"month": "2027-07"}]
        self.assertEqual(requirement(ledger(workbook), "r1.general_medicine")["expected_months"], 2)
        workbook["target_year"], workbook["months"] = 2026, [{"month": "2026-07"}]
        self.assertEqual(workbook, original)
        for invalid in ({}, {"months": []}, {"months": [{"month": "invalid"}]},
                        {"months": [{"month": "2026-07"}], "target_year": 2027}):
            with self.assertRaisesRegex(ValueError, "planning"):
                ledger(invalid)

    def test_raw_conflicts_blank_loa_and_unsafe_identity_never_credit(self):
        history = resident([("2026-01", "TTSH General Medicine"), ("2026-02", "TTSH General Medicine")])
        other = resident([("2026-01", "LOA"), ("2026-02", None)], sheet="Other")
        result = ledger(book([history, other]))
        self.assertEqual([item["status"] for item in result["residents"][0]["months"]], ["pending", "pending"])
        self.assertEqual(requirement(result, "r1.general_medicine")["remaining_months"], None)
        workbook = book([history])
        workbook["issues"] = [{"code": "duplicate_mcr", "records": [{"source": history["source"]},
                               {"source": workbook["residents"][0]["source"]}]}]
        result = ledger(workbook)["residents"][0]
        self.assertFalse(result["identity_safe"])
        self.assertEqual(result["months"], [])
        self.assertIn("unsafe_identity", result["warnings"])
        workbook["issues"][0]["records"] = [{"source": history["source"]}]
        result = ledger(workbook)["residents"][0]
        self.assertTrue(result["identity_safe"])
        self.assertEqual(result["months"], [])
        self.assertEqual(result["warnings"], ["unsafe_historical_identity_evidence_excluded"])

    def test_r1_routes_are_alternatives_and_combined_months_not_split(self):
        months = [(f"2025-{i:02d}", "NUH Medicine & Neurology" if i <= 6 else "IMH Inpatient Psychiatry")
                  for i in range(1, 13)]
        result = ledger(book([resident(months)]))
        self.assertEqual([route["evidence_status"] for route in result["residents"][0]["r1_routes"]], ["partial", "supported"])
        self.assertEqual(requirement(result, "r1.general_medicine")["evidence_status"], "not_evidenced")
        separate = [(f"2025-{i:02d}", "TTSH General Medicine" if i <= 4 else "NNI Neurology" if i <= 6
                     else "IMH Inpatient Psychiatry") for i in range(1, 13)]
        routes = ledger(book([resident(separate)]))["residents"][0]["r1_routes"]
        self.assertEqual([route["evidence_status"] for route in routes], ["supported", "partial"])
        partial = ledger(book([resident(months[:3])]))
        self.assertEqual(requirement(partial, "r1.medicine_neurology")["expected_months"], 3)
        self.assertEqual(requirement(partial, "r1.neurology")["expected_months"], 0)

    def test_r3_loa_pauses_but_gaps_other_postings_and_sites_cannot_pool(self):
        months = [(f"2025-{i:02d}", "IMH Continuity Clinic" if i <= 6 else "LOA") for i in range(1, 13)]
        result = ledger(book([resident(months, "R3")]))
        self.assertEqual(requirement(result, "r3.continuity_clinic")["remaining_months"], 6)
        tail = [(f"2026-{i:02d}", "IMH Continuity Clinic") for i in range(1, 7)]
        result = ledger(book([resident(months + tail, "R3")]))
        self.assertEqual(requirement(result, "r3.continuity_clinic")["expected_months"], 12)
        cross_annual = book([resident(months, "R2,R3", "Earlier"), resident(tail, "R3", "Later")])
        self.assertEqual(requirement(ledger(cross_annual), "r3.continuity_clinic")["expected_months"], 12)
        for break_value in (None, "Unknown department", "TTSH Continuity Clinic"):
            changed = list(months)
            changed[7] = ("2025-08", break_value)
            summary = requirement(ledger(book([resident(changed + tail, "R3")])), "r3.continuity_clinic")
            self.assertEqual(summary["expected_months"], 6)
            self.assertGreaterEqual(len(summary["continuity_groups"]), 2)
        gap = months[:6] + tail
        self.assertEqual(requirement(ledger(book([resident(gap, "R3")])), "r3.continuity_clinic")["expected_months"], 6)

    def test_year_confirmation_remediation_stale_and_programme_validation(self):
        history = resident([("2026-01", "TTSH General Medicine")], "R3")
        workbook = book([history])
        self.assertEqual(ledger(workbook)["residents"][0]["months"][0]["reasons"], ["requirement_year_unconfirmed"])
        reviewed = evaluate_review(workbook, ReviewStore(version=1, decisions=[]))
        candidate = next(item for item in reviewed["catalogue"] if item["label"] == "TTSH General Medicine")
        decision = {"kind": "resident", "context": reviewed["entries"][0]["context"],
                    "target": {key: candidate[key] for key in ("key", "signature")}, "requirement_year": "R1"}
        self.assertEqual(requirement(ledger(workbook, [decision]), "r1.general_medicine")["expected_months"], 1)
        stale = deepcopy(decision)
        stale["target"]["signature"] = "changed"
        self.assertEqual(ledger(workbook, [stale])["residents"][0]["months"][0]["status"], "pending")
        history["postings"][0]["value"] += " (Remediation)"
        reviewed = evaluate_review(workbook, ReviewStore(version=1, decisions=[]))
        decision["context"] = reviewed["entries"][0]["context"]
        self.assertIn("remediation_credit_review", ledger(workbook, [decision])["residents"][0]["months"][0]["reasons"])
        invalid = book([resident([("2026-01", "TTSH Geriatric Psychiatry")], "R2")])
        self.assertEqual(ledger(invalid)["residents"][0]["months"][0]["reasons"], ["institution_not_allowed"])


if __name__ == "__main__":
    unittest.main()
