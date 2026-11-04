import unittest
from copy import deepcopy

from fastapi.testclient import TestClient
from main import app
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
    def test_intake_slots_have_full_r1_requirements_without_historical_credit(self):
        from test_workbook_import import IncomingIntakeTests
        workbook = IncomingIntakeTests().parse([("Resident 1", None, "R1", 2027)], history_placeholder=True)
        original = deepcopy(workbook)
        result = ledger(workbook)
        for person in result["residents"]:
            self.assertTrue(person["identity_safe"])
            self.assertEqual(person["warnings"], [])
            self.assertEqual(person["months"], [])
            r1 = [r for r in person["requirements"] if r["requirement_year"] == "R1"]
            self.assertEqual({r["remaining_months"] for r in r1}, {2, 4, 6})
            self.assertTrue(all(r["expected_months"] == 0 for r in r1))
        self.assertEqual(len(result["residents"]), 24)
        entries = evaluate_review(workbook, ReviewStore(version=1, decisions=[]), "timetable")["entries"]
        self.assertTrue(all("kind" not in source for entry in entries for source in entry["sources"]))
        self.assertEqual(workbook, original)
        duplicate = IncomingIntakeTests().parse([("Resident 1", None, "R1", 2027)] * 2)
        self.assertTrue(all(not p["identity_safe"] for p in ledger(duplicate)["residents"]))
        forged = deepcopy(workbook)
        forged["residents"][0]["slot_id"] = "intake-2026-slot-01"
        self.assertFalse(ledger(forged)["residents"][0]["identity_safe"])
        known = book([resident([("2026-06", "TTSH General Medicine")])])
        for code in ("unclear_intake", "excess_intake"):
            known["issues"] = [{"code": code, "records": [{"source": known["residents"][0]["source"]}]}]
            self.assertTrue(ledger(known)["residents"][0]["identity_safe"])
            self.assertEqual(requirement(ledger(known), "r1.general_medicine")["expected_months"], 1)

    def test_historical_timing_notes_group_proven_exceptions_without_changing_credit_or_readiness(self):
        from test_r1_solver import r1_book, set_history
        from r1_solver import draft_r1_schedule
        workbook = r1_book()
        history = set_history(workbook, ["SGH General Medicine"] + ["LOA"] * 5 + ["IMH Inpatient Psychiatry"] * 6)
        # A merged source can support several months; display each reference once.
        for posting in history["postings"][6:]:
            posting["source"] = {"sheet": "History", "row": 3, "column": "J"}
        original = deepcopy(workbook)
        result = ledger(workbook)
        person = result["residents"][0]
        self.assertEqual(person["historical_notes"], [{"code": "historical_r1_timing_exception",
            "posting": "IMH Inpatient Psychiatry", "start": "2027-01", "end": "2027-06", "months": 6,
            "sources": [{"sheet": "History", "row": 3, "column": "J"}]}])
        self.assertEqual(person["warnings"], [])
        self.assertEqual(requirement(result, "r1.general_medicine")["remaining_months"], 3)
        self.assertEqual(requirement(result, "r1.inpatient_psychiatry")["remaining_months"], 0)
        self.assertEqual(draft_r1_schedule(workbook, ReviewStore(version=1, decisions=[]))["status"], "optimal")
        self.assertEqual(workbook, original)
        for uncertainty in ("missing_intake", "missing_month", "blank_month", "unresolved_month", "pre_intake_credit", "unsafe_history"):
            with self.subTest(uncertainty=uncertainty):
                changed = deepcopy(workbook)
                raw_history = changed["annual_sheets"][0]["residents"][0]
                if uncertainty == "missing_intake":
                    changed["residents"][0]["intake"] = None
                elif uncertainty == "missing_month":
                    raw_history["postings"].pop(1)
                elif uncertainty in {"blank_month", "unresolved_month"}:
                    raw_history["postings"][1].update(status="blank" if uncertainty == "blank_month" else "posting",
                                                      value=None if uncertainty == "blank_month" else "Unknown posting")
                elif uncertainty == "pre_intake_credit":
                    changed["residents"][0]["intake"] = "2027"
                else:
                    changed["issues"] = [{"code": "duplicate_mcr", "records": [{"source": raw_history["source"]}]}]
                self.assertEqual(ledger(changed)["residents"][0]["historical_notes"], [])
        normal = r1_book()
        set_history(normal, ["SGH General Medicine"] * 4 + ["SGH Neurology"] * 2 + ["IMH Inpatient Psychiatry"] * 6)
        self.assertEqual(ledger(normal)["residents"][0]["historical_notes"], [])

    def test_endpoint_uses_workbook_context_serializes_evidence_and_validates_requests(self):
        workbook = book([resident([("2026-06", "TTSH General Medicine")])], "2026-07")
        original = deepcopy(workbook)
        with TestClient(app) as client:
            response = client.post("/api/requirement-ledger", json={"workbook": workbook, "store": {"version": 1, "decisions": []}})
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(result["cutoff"], "2026-06")
            self.assertEqual(result["basis"], "projected_expected_not_certified")
            self.assertEqual(result["residents"][0]["months"][0]["evidence"][0]["source"], workbook["annual_sheets"][0]["residents"][0]["postings"][0]["source"])
            for payload in ({"workbook": {}, "store": {"version": 1, "decisions": []}},
                            {"workbook": workbook, "store": {"version": 2, "decisions": []}}):
                invalid = client.post("/api/requirement-ledger", json=payload)
                self.assertEqual(invalid.status_code, 422)
            self.assertIn("Import the workbook again", client.post("/api/requirement-ledger", json={"workbook": {}, "store": {"version": 1, "decisions": []}}).json()["detail"])
        self.assertEqual(workbook, original)

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
        self.assertEqual(requirement(result, "r1.general_medicine")["remaining_months"], 4)
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
        self.assertEqual(requirement(ledger(workbook), "r1.general_medicine")["expected_months"], 1)
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
        self.assertEqual(requirement(ledger(workbook), "r1.general_medicine")["expected_months"], 1)
        self.assertEqual(requirement(ledger(workbook, [decision]), "r1.general_medicine")["expected_months"], 1)
        invalid = book([resident([("2026-01", "TTSH Geriatric Psychiatry")], "R2")])
        self.assertEqual(ledger(invalid)["residents"][0]["months"][0]["reasons"], ["institution_not_allowed"])

    def test_earlier_electives_and_remediation_count_without_bypassing_ambiguity(self):
        history = resident([(f"2026-{month:02d}", "IMH Geriatric Psychiatry (Remediation)" if month <= 9
                            else "IMH ANDS (Elective)") for month in range(7, 13)], "R3")
        earlier = resident([(f"2025-{month:02d}", "IMH Geriatric Psychiatry") for month in range(1, 4)], "R2", "Earlier")
        workbook = book([earlier, history])
        workbook["postings"]["core"].append({"posting": "IMH Geriatric Psychiatry", "residency_year": "R2",
                                            "source": {"sheet": "Reference", "row": 20}})
        workbook["postings"]["electives"] = [{"institution": "IMH", "elective": "ANDS", "residency_year": year,
                                             "source": {"sheet": "Reference", "row": i + 21}, "remarks": []}
                                            for i, year in enumerate(("R2", "R5"))]
        original = deepcopy(workbook)
        result = ledger(workbook)
        self.assertEqual(requirement(result, "r2.geriatric_psychiatry")["expected_months"], 6)
        self.assertEqual(requirement(result, "r2.geriatric_psychiatry")["remaining_months"], 0)
        self.assertEqual(requirement(result, "r2.elective")["expected_months"], 3)
        self.assertEqual(requirement(result, "r2.elective")["remaining_months"], 0)
        self.assertEqual(requirement(result, "r5.elective")["expected_months"], 0)
        self.assertEqual(workbook, original)
        workbook["postings"]["electives"] = workbook["postings"]["electives"][1:]
        self.assertTrue(all(m["status"] == "pending" for m in ledger(workbook)["residents"][0]["months"] if m["month"] >= "2026-10"))
        workbook = original
        workbook["postings"]["core"].append({"posting": "IMH Geriatric Psychiatry", "residency_year": "R1",
                                            "source": {"sheet": "Reference", "row": 30}})
        result = ledger(workbook)
        self.assertTrue(all(m["status"] == "pending" for m in result["residents"][0]["months"] if "2026-07" <= m["month"] <= "2026-09"))


if __name__ == "__main__":
    unittest.main()
