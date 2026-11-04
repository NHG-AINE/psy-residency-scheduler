import unittest
from copy import deepcopy

from cluster_coverage import cluster_coverage
from requirement_ledger import build_requirement_ledger
from scheduler_inputs import prepare_scheduler_inputs
from scheduler import draft_schedule
from tests.test_requirement_ledger import book, resident
from tests.test_r1_solver import STORE, r1_book, set_history


class ClusterCoverageTests(unittest.TestCase):
    def test_mapping_and_only_recognised_r1_to_r4_months_grant_credit(self):
        for cluster, sites in (("NHG", ("IMH", "TTSH", "KTPH", "WH")),
                               ("SHS", ("CGH", "SGH", "SKH", "KKH", "NNI")),
                               ("NUHS", ("NUH", "NTFGH", "AH"))):
            for site in sites:
                with self.subTest(site=site):
                    month = {"status": "expected", "requirement_year": "R2", "institution": site}
                    self.assertEqual(cluster_coverage([month, month])["visited"], [cluster])
        excluded = [{"status": status, "requirement_year": "R1", "institution": "NNI"}
                    for status in ("pending", "loa", "blank")]
        excluded += [{"status": "expected", "requirement_year": year, "institution": "NUH"}
                     for year in ("R5", None)]
        excluded.append({"status": "expected", "requirement_year": "R1", "institution": "Unknown"})
        self.assertEqual(cluster_coverage(excluded), {"visited": [], "missing": ["NHG", "SHS", "NUHS"]})

    def test_ledger_and_scheduler_use_cutoff_history_not_future_or_unresolved_labels(self):
        history = resident([("2026-01", "TTSH General Medicine"), ("2026-02", "NNI Neurology"),
                            ("2026-03", "NNI Neurology"), ("2026-04", "LOA"),
                            ("2026-05", "NUH unclear posting")])
        r5 = resident([("2026-06", "NUH Geriatric Psychiatry")], "R5", row=4)
        future = resident([("2027-07", "NUH Medicine & Neurology")], "R1", row=5)
        workbook = book([history, r5, future])
        workbook["postings"]["core"].append({"posting": "NUH Geriatric Psychiatry", "residency_year": "R5",
                                             "source": {"sheet": "Reference", "row": 30}})
        original = deepcopy(workbook)
        expected = {"visited": ["NHG", "SHS"], "missing": ["NUHS"]}
        self.assertEqual(build_requirement_ledger(workbook, STORE)["residents"][0]["cluster_coverage"], expected)
        self.assertEqual(prepare_scheduler_inputs(workbook, STORE)["residents"][0]["cluster_coverage"], expected)
        self.assertEqual(workbook, original)

    def test_draft_projected_coverage_is_separate_and_excludes_unscheduled_carryforward(self):
        workbook = r1_book()
        set_history(workbook, ["TTSH General Medicine"] * 4 + ["NNI Neurology"] * 2)
        for posting in workbook["postings"]["core"]:
            if "Inpatient" in posting["posting"] and not posting["posting"].startswith("NUH "):
                posting["max"] = "0"
        original = deepcopy(workbook)
        historical = {"visited": ["NHG", "SHS"], "missing": ["NUHS"]}
        result = draft_schedule(workbook, STORE)
        self.assertEqual(result["status"], "optimal")
        coverage = result["residents"][0]["cluster_coverage"]
        self.assertEqual(coverage["historical"], historical)
        self.assertEqual(coverage["projected"], {"visited": ["NHG", "SHS", "NUHS"], "missing": []})
        self.assertEqual(build_requirement_ledger(workbook, STORE)["residents"][0]["cluster_coverage"], historical)
        self.assertEqual(workbook, original)
        for month in workbook["residents"][0]["postings"]:
            month.update(status="loa", value="LOA")
        result = draft_schedule(workbook, STORE)
        self.assertEqual(result["status"], "optimal")
        self.assertTrue(result["residents"][0]["carryforward"])
        self.assertEqual(result["residents"][0]["cluster_coverage"]["projected"], historical)


if __name__ == "__main__":
    unittest.main()
