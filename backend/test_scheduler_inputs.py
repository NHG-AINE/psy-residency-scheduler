import unittest
from copy import deepcopy

from history_review import ReviewStore
from programme_requirements import validate_posting
from requirement_ledger import build_requirement_ledger
from scheduler_inputs import prepare_scheduler_inputs
from test_requirement_ledger import book, resident
import test_workbook_import


STORE = ReviewStore(version=1, decisions=[])


def planning_book(history=(), planning="2027-07"):
    workbook = book(list(history), planning)
    workbook["postings"]["core"] = [row for row in workbook["postings"]["core"]
                                      if validate_posting(row["residency_year"], {**row, "label": row["posting"], "category": "core"})["valid"]]
    for row in workbook["postings"]["core"]:
        row["duration_months"] = str(validate_posting(row["residency_year"], {**row, "label": row["posting"], "category": "core"})["required_months"])
        row["max"] = None
    workbook["residents"][0]["postings"] = resident([(planning, None)], sheet="Planning")["postings"]
    return workbook


class SchedulerInputsTests(unittest.TestCase):
    def test_composes_named_and_imported_slots_with_dynamic_period_and_full_ledger(self):
        workbook = planning_book([resident([("2026-05", "TTSH General Medicine")]),
                                  resident([("2026-06", "IMH Continuity Clinic")], "R3", "Clinic")], "2026-07")
        imported = test_workbook_import.IncomingIntakeTests().parse([("Named Incoming", "NEW", "R1", 2027)])
        # Reuse importer-produced vacancies, in their actual intake/planning year.
        workbook["target_year"], workbook["months"] = 2027, imported["months"]
        workbook["residents"][0]["postings"] = resident([(m["month"], None) for m in workbook["months"]], sheet="Planning")["postings"]
        workbook["residents"].extend(imported["residents"])
        workbook["requests"] = [{"posting_request": "Prefer October", "period": "Oct"}]
        original = deepcopy(workbook)
        result = prepare_scheduler_inputs(workbook, STORE)
        expected = build_requirement_ledger(workbook, STORE)
        self.assertEqual(result["cutoff"], "2027-06")
        self.assertEqual(result["planning_months"], workbook["months"])
        self.assertEqual(result["requests"], workbook["requests"])
        self.assertEqual(len(result["residents"]), 25)
        for actual, progress in zip(result["residents"], expected["residents"]):
            for field in ("source", "recorded_year", "requirements", "r1_routes", "months", "slot_id"):
                self.assertEqual(actual[field], progress[field])
        self.assertTrue(result["residents"][1]["input_ready"])
        self.assertTrue(result["residents"][-1]["input_ready"])
        earlier = planning_book([resident([("2026-06", "TTSH General Medicine")])], "2026-07")
        self.assertEqual(prepare_scheduler_inputs(earlier, STORE)["cutoff"], "2026-06")
        self.assertEqual(workbook, original)

    def test_planning_loa_unavailable_but_blank_and_existing_posting_schedulable(self):
        workbook = planning_book([resident([("2026-06", "TTSH General Medicine")])])
        raw = resident([("2027-07", "LOA"), ("2027-08", None), ("2027-09", "TTSH General Medicine")], sheet="Planning")
        workbook["months"] = [{"month": p["month"]} for p in raw["postings"]]
        workbook["residents"][0]["postings"] = raw["postings"]
        workbook["residents"][0]["residency_year"] = "R2,R3"
        result = prepare_scheduler_inputs(workbook, STORE)["residents"][0]
        self.assertEqual([m["available"] for m in result["availability"]], [False, True, True])
        self.assertEqual(result["availability"][2]["evidence"][0]["value"], "TTSH General Medicine")
        self.assertTrue(result["input_ready"])
        self.assertEqual(result["recorded_years"], ["r2", "r3"])
        workbook["residents"][0]["postings"].pop()
        missing = prepare_scheduler_inputs(workbook, STORE)["residents"][0]
        self.assertFalse(missing["availability"][-1]["available"])
        self.assertFalse(missing["input_ready"])

    def test_catalogue_preserves_exact_options_capacity_and_policy_review(self):
        workbook = planning_book([resident([("2026-06", "TTSH General Medicine")])])
        workbook["postings"]["electives"] = [{"residency_year": "R2", "institution": "IMH", "elective": "ANDS",
            "source": {"sheet": "Reference", "row": 100},
            "remarks": [{"text": "Original elective condition", "source": {"sheet": "Reference", "row": 101}}]}]
        core = workbook["postings"]["core"]
        core.extend([{"residency_year": "R2", "posting": "Electives", "duration_months": "3",
                       "source": {"sheet": "Reference", "row": 110}, "remarks": "Original summary condition"},
                     {"residency_year": "R5", "posting": None, "duration_months": None, "max": None, "remarks": None,
                      "source": {"sheet": "Reference", "row": 111}}])
        core[0]["max"], core[1]["max"] = None, "0"
        core[0]["remarks"] = "To be completed in the first 6 months of R1"
        result = prepare_scheduler_inputs(workbook, STORE)
        options = result["catalogue_options"]
        self.assertEqual([o["capacity"] for o in options[:2]], [None, 0])
        self.assertEqual(options[0]["label"], core[0]["posting"])
        self.assertEqual(options[0]["institution"], "TTSH")
        self.assertEqual(options[0]["training_months"], (1, 6))
        self.assertEqual(options[0]["duration_months"], 4)
        self.assertTrue(options[0]["policy_review_required"])
        self.assertEqual(result["policy_reviews"][0]["remarks"], core[0]["remarks"])
        self.assertEqual(result["catalogue_summaries"], [core[-2]])
        self.assertTrue(any(review["remarks"] == "Original summary condition" for review in result["policy_reviews"]))
        self.assertEqual(len(options), len(core) - 2 + 1)
        self.assertTrue(result["input_ready"])  # Input readiness never certifies policy enforcement.
        self.assertEqual(len(result["residents"][0]["r1_routes"]), 2)
        elective = options[-1]
        self.assertEqual((elective["label"], elective["institution"], elective["duration_months"]), ("IMH ANDS", "IMH", 3))
        self.assertEqual(elective["remarks"], workbook["postings"]["electives"][0]["remarks"])
        self.assertTrue(elective["policy_review_required"])
        for field, value, reason in (("posting", "KKH General Medicine", "institution_not_allowed"),
                                     ("posting", None, "invalid_catalogue_label"),
                                     ("residency_year", "R1,R2", "unknown_requirement_year"),
                                     ("duration_months", "3", "programme_duration_mismatch"),
                                     ("duration_months", "bad", "invalid_duration"),
                                     ("max", "-1", "invalid_capacity"), ("max", "1.5", "invalid_capacity")):
            with self.subTest(field=field, value=value):
                changed = deepcopy(workbook)
                changed["postings"]["core"][0][field] = value
                prepared = prepare_scheduler_inputs(changed, STORE)
                self.assertFalse(prepared["input_ready"])
                self.assertIn(reason, prepared["catalogue_options"][0]["reasons"])
                self.assertEqual(prepared["blockers"][0]["source"], core[0]["source"])

    def test_readiness_preserves_relevant_sourced_blockers_without_global_warning_poisoning(self):
        workbook = planning_book([resident([("2026-06", "Unknown department")])])
        workbook["issues"] = [{"code": "missing_mcr", "records": [{"source": {"sheet": "Unrelated", "row": 99}}]},
                              {"code": "unmatched_request", "source": {"sheet": "Request", "row": 9}},
                              {"code": "unmapped_posting", "sources": [{"sheet": "Unrelated", "row": 8}]}]
        result = prepare_scheduler_inputs(workbook, STORE)
        self.assertFalse(result["input_ready"])
        self.assertEqual(result["residents"][0]["blockers"][0]["sources"], [workbook["annual_sheets"][0]["residents"][0]["postings"][0]["source"]])
        safe = planning_book([resident([("2026-06", "TTSH General Medicine")])])
        safe["issues"] = workbook["issues"]
        self.assertTrue(prepare_scheduler_inputs(safe, STORE)["input_ready"])
        safe["issues"].append({"code": "duplicate_mcr", "records": [{"source": safe["residents"][0]["source"]}]})
        unsafe = prepare_scheduler_inputs(safe, STORE)
        self.assertEqual(len(unsafe["residents"]), 1)
        self.assertFalse(unsafe["input_ready"])
        self.assertEqual(unsafe["residents"][0]["blockers"][0], {"code": "unsafe_identity", "source": safe["residents"][0]["source"]})
        unknown = prepare_scheduler_inputs(planning_book(), STORE)
        self.assertEqual(unknown["residents"][0]["blockers"][0]["code"], "historical_progress_unknown")


if __name__ == "__main__":
    unittest.main()
