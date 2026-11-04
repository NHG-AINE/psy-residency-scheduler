import unittest
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from fastapi.testclient import TestClient
from openpyxl import Workbook
from main import app
from workbook_import import MAX_UPLOAD_BYTES, WorkbookError, parse_workbook, review_import, match_posting, posting_catalogue


def workbook_bytes(edit=None):
    w = Workbook()
    w.remove(w.active)
    for year, offset, h in ((2026, 2, 3), (2027, 4, 2)):
        s = w.create_sheet(f"Jul {year} - Jun {year + 1}")
        for col, label in enumerate(("Name", "MCR No.", "Residency Year"), offset):
            s.cell(h, col, label)
        for i in range(12):
            col = offset + 3 + i
            s.cell(h - 1, col, datetime(year + (i + 6) // 12, (i + 6) % 12 + 1, 1))
            s.cell(h, col, "7 Jul - 5 Aug (original display text)")
            s.cell(h + 1, col, "LOA" if i == 0 else "Posting")
        for col, value in enumerate(("Example Resident", "M12345A", "R2,R3"), offset):
            s.cell(h + 1, col, value)
        if year == 2027:
            s.cell(h - 1, offset + 15, "Remarks")
            s.merge_cells(start_row=h - 1, end_row=h, start_column=offset + 15, end_column=offset + 15)
            s.cell(h + 1, offset + 15, "Preserved merged header remark")
            s.merge_cells(start_row=h + 1, end_row=h + 1, start_column=offset + 4, end_column=offset + 5)
    s = w.create_sheet("Request")
    s.append(["Name", "MCR No.", "Residency Year", "Posting Request", "Period", "Remarks"])
    s.append(["Example Resident", "M12345A", "R2,R3", "Free text request", "Either Jul or Oct", "Unconfirmed"])
    s = w.create_sheet("Postings")
    s.append(["R2 Electives", None, None, "Residency Year", "Core Posting", "Duration (Months)", "Max", "Remarks"])
    s.append(["Raw elective note", None, None, "R2", "Core example", 3, 2, "Original condition"])
    if edit:
        edit(w)
    s.append([None, None, None, None, "Standalone posting", 6])
    stream = BytesIO()
    w.save(stream)
    return stream.getvalue()


class WorkbookImportTests(unittest.TestCase):
    def test_history_matches_mcr_preserves_blanks_and_excludes_future(self):
        def edit(w):
            target = w["Jul 2027 - Jun 2028"]
            target["D3"] = "  EXAMPLE   Resident "
            target["E3"] = " m12345a "
            target["R3"] = None
            future = w.copy_worksheet(target)
            future.title = "Jul 2028 - Jun 2029"
            for cell in future[1]:
                if isinstance(cell.value, datetime):
                    cell.value = cell.value.replace(year=cell.value.year + 1)
        r = parse_workbook(workbook_bytes(edit))
        self.assertEqual([h["year"] for h in r["histories"]], [2026])
        history = r["histories"][0]["residents"][0]
        self.assertEqual(history["match_status"], "matched")
        self.assertEqual(history["matched_resident_source"], r["residents"][0]["source"])
        self.assertEqual(r["requests"][0]["match_status"], "matched")
        self.assertEqual(r["residents"][0]["mcr"], " m12345a ")
        self.assertEqual(len(r["residents"][0]["postings"]), 12)
        self.assertIsNone(r["residents"][0]["postings"][-1]["value"])
        self.assertEqual(r["months"][1]["month"], "2027-08")
        self.assertEqual(r["months"][1]["date_range_text"], "7 Jul - 5 Aug (original display text)")
        unmapped = next(i for i in r["issues"] if i["code"] == "unmapped_posting")
        self.assertEqual(unmapped["severity"], "info")
        self.assertNotIn("LOA", unmapped["values"])

    def test_monthly_status_preserves_raw_entries_and_limits_reference_checks(self):
        values = ["LOA", " loa ", "LoA", None, "", " \t ", "LOA pending", "Repeat R3 TBC", " core EXAMPLE ", "Unknown", "Posting", "LOA/Posting"]

        def edit(w):
            sheet = w["Jul 2026 - Jun 2027"]
            for column, value in enumerate(values, 5):
                sheet.cell(4, column).value = value
            w["Postings"]["E2"] = "  Core Example  "

        result = parse_workbook(workbook_bytes(edit))
        entries = result["histories"][0]["residents"][0]["postings"]
        self.assertEqual([p["status"] for p in entries], ["loa"] * 3 + ["blank"] * 3 + ["posting"] * 6)
        # Excel stores an empty string as an empty cell; all other text stays exact.
        self.assertEqual([p["value"] for p in entries], values[:4] + [None] + values[5:])
        self.assertEqual([p["month"] for p in entries], [f"2026-{m:02d}" for m in range(7, 13)] + [f"2027-{m:02d}" for m in range(1, 7)])
        self.assertEqual([p["source"] for p in entries], [{"sheet": "Jul 2026 - Jun 2027", "row": 4, "column": chr(c)} for c in range(ord("E"), ord("Q"))])
        self.assertEqual(result["residents"][0]["postings"][0]["status"], "loa")
        issue = next(i for i in result["issues"] if i["code"] == "unmapped_posting")
        self.assertEqual(set(issue["values"]), {"LOA pending", "Repeat R3 TBC", "Unknown", "Posting", "LOA/Posting"})
        self.assertTrue(all(p["source"] not in issue["sources"] for p in entries[:6]))

    def test_identity_problems_withhold_matching_without_dropping_rows(self):
        def duplicate(w):
            s = w["Jul 2027 - Jun 2028"]
            s["D4"], s["E4"], s["F4"] = "Example Resident", "M12345A", "R3"
        cases = [
            (lambda w: setattr(w["Jul 2027 - Jun 2028"]["E3"], "value", None), "missing_mcr"),
            (duplicate, "duplicate_mcr"),
            (lambda w: setattr(w["Jul 2026 - Jun 2027"]["B4"], "value", "Different Name"), "conflicting_identity"),
            (lambda w: setattr(w["Jul 2026 - Jun 2027"]["C4"], "value", "MP1234A"), "conflicting_identity"),
            (lambda w: setattr(w["Jul 2026 - Jun 2027"]["C4"], "value", None), "missing_mcr"),
        ]
        for edit, code in cases:
            with self.subTest(code=code, edit=edit):
                r = parse_workbook(workbook_bytes(edit))
                history = r["histories"][0]["residents"][0]
                self.assertNotEqual(history["match_status"], "matched")
                self.assertIsNone(history["matched_resident_source"])
                self.assertIn(code, [i["code"] for i in r["issues"]])
                self.assertEqual(len(history["postings"]), 12)

    def test_identity_conflicts_group_related_rows_but_keep_distinct_conflicts_separate(self):
        def record(name, mcr, sheet, row):
            return {"name": name, "mcr": mcr, "source": {"sheet": sheet, "row": row}, "postings": []}
        current = [record("Alex Example", " M001 ", "Current", 3), record("Jamie Example", "M002", "Current", 4)]
        history = [record("Alex Example (SAF)", "m001", "History", 5), record("Jamie Example", "M003", "History", 6)]
        requests = [record("Alex Example", "M001", "Request", 7)]
        result = review_import({"residents": current, "histories": [{"residents": history}], "requests": requests, "postings": {"core": []}})
        conflicts = [i for i in result["issues"] if i["code"] == "conflicting_identity"]
        self.assertEqual(len(conflicts), 2)
        self.assertEqual([len(i["records"]) for i in conflicts], [3, 2])
        originals = current + history + requests
        reported = [r for issue in conflicts for r in issue["records"]]
        self.assertCountEqual(reported, [{"name": r["name"], "mcr": r["mcr"], "source": r["source"]} for r in originals])
        self.assertEqual(reported[0]["mcr"], " M001 ")
        self.assertEqual(len(current) + len(history) + len(requests), 5)
        # Parenthetical suffixes stay significant; grouping must not relax matching.
        self.assertTrue(all(r["match_status"] == "ambiguous" for r in history + requests))
        self.assertTrue(all(r["matched_resident_source"] is None for r in history + requests))

    def test_duplicates_are_grouped_per_mcr_per_annual_sheet_and_missing_rows_stay_visible(self):
        def record(name, mcr, sheet, row):
            return {"name": name, "mcr": mcr, "source": {"sheet": sheet, "row": row}, "postings": []}
        current = [record("Alex", "M001", "Current", n) for n in (3, 4, 5)]
        history = [record("Alex", "M001", "History", n) for n in (6, 7)]
        requests = [record("Missing MCR", None, "Request", 8), record(None, "M009", "Request", 9), record("Unmatched", "M010", "Request", 10)]
        result = review_import({"residents": current, "histories": [{"residents": history}], "requests": requests, "postings": {"core": []}})
        duplicates = [i for i in result["issues"] if i["code"] == "duplicate_mcr"]
        self.assertEqual([len(i["records"]) for i in duplicates], [3, 2])
        self.assertEqual([{r["source"]["sheet"] for r in i["records"]} for i in duplicates], [{"Current"}, {"History"}])
        for code, request in zip(("missing_mcr", "missing_name", "unmatched_request"), requests):
            issue = next(i for i in result["issues"] if i["code"] == code)
            self.assertEqual(issue["records"], [{"name": request["name"], "mcr": request["mcr"], "source": request["source"]}])
        self.assertEqual(requests[-1]["match_status"], "unmatched")
        self.assertTrue(all(r["match_status"] == "ambiguous" for r in history))

    def test_request_mcr_is_checked_across_years_without_linking_future_residents(self):
        def edit(w):
            w["Jul 2027 - Jun 2028"]["D3"] = "New Resident"
            w["Jul 2027 - Jun 2028"]["E3"] = "M99999A"
            w["Request"]["A2"] = "New Resident"
            w["Request"]["B2"] = " m99999a "
            w["Request"].append(["Unknown Resident", "M00000X", "R1", "Example", "July"])
        result = parse_workbook(workbook_bytes(edit), 2026)
        issues = [i for i in result["issues"] if i["code"] == "unmatched_request"]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["records"][0]["mcr"], "M00000X")
        self.assertEqual(result["requests"][0]["match_status"], "unmatched")
        self.assertIsNone(result["requests"][0]["matched_resident_source"])
        self.assertEqual(result["histories"], [])
        self.assertEqual(result["residents"][0]["mcr"], "M12345A")

    def test_posting_comparison_ignores_outer_spaces_and_case_but_preserves_text(self):
        def edit(w):
            w["Postings"]["E2"] = "  Core Example  "
            w["Jul 2027 - Jun 2028"]["G3"] = " core EXAMPLE "
            w["Jul 2027 - Jun 2028"]["J3"] = "Core Example (Elective)"
        result = parse_workbook(workbook_bytes(edit))
        issue = next(i for i in result["issues"] if i["code"] == "unmapped_posting")
        self.assertNotIn(" core EXAMPLE ", issue["values"])
        self.assertIn("Core Example (Elective)", issue["values"])
        self.assertEqual(result["residents"][0]["postings"][0]["value"], " core EXAMPLE ")
        self.assertEqual(result["postings"]["core"][0]["posting"], "  Core Example  ")

    def test_missing_reference_issue_uses_full_catalogue_without_conflating_year_or_credit_review(self):
        values = [" SITE Core ", "SITE Elective(ELECTIVE)", "SITE Ambiguous", "SITE Future", "SITE Core (Remediation)",
                  "SITE Missing (Elective)", "SITE Missing (Elective)", "SITE Missing (Remediation)", "LOA", None, "", " "]
        def edit(w):
            reference = w["Postings"]
            for row, (year, label) in enumerate((("R2", "SITE Core"), ("R5", "SITE Core"),
                                                 ("R1", "SITE Ambiguous"), ("R2", "SITE Ambiguous"), ("R5", "SITE Future")), 2):
                reference.cell(row, 4, year)
                reference.cell(row, 5, label)
            reference["A2"], reference["A3"] = "SITE", "- Elective"
            reference["B1"], reference["B2"], reference["B3"] = "R5 Electives", "SITE", "- Elective"
            history = w["Jul 2026 - Jun 2027"]
            history["D4"] = "R3"
            for column, value in enumerate(values, 5):
                history.cell(4, column).value = value
            target = w["Jul 2027 - Jun 2028"]
            for merged in list(target.merged_cells.ranges):
                target.unmerge_cells(str(merged))
            for column in range(7, 19):
                target.cell(3, column).value = None
        result = parse_workbook(workbook_bytes(edit))
        postings = result["histories"][0]["residents"][0]["postings"]
        self.assertTrue(all(posting["catalogue_match"]["candidates"] for posting in postings[:5]))
        self.assertEqual(postings[2]["catalogue_match"]["status"], "ambiguous")
        self.assertEqual(postings[3]["catalogue_match"]["status"], "needs_review")
        self.assertIn("remediation_credit_review", postings[4]["catalogue_match"]["reasons"])
        issue = next(issue for issue in result["issues"] if issue["code"] == "unmapped_posting")
        self.assertEqual(issue["title"], "Posting labels without a catalogue reference")
        self.assertIn("core or elective catalogue", issue["message"])
        self.assertEqual(issue["values"], values[5:8])
        self.assertEqual(issue["sources"], [posting["source"] for posting in postings[5:8]])
        self.assertEqual(issue["source"], postings[5]["source"])
        self.assertEqual([posting["value"] for posting in postings[:9]], values[:9])

    def test_unmapped_postings_retain_every_distinct_original_cell_source(self):
        def edit(w):
            w["Jul 2026 - Jun 2027"]["F4"] = " loa "
        result = parse_workbook(workbook_bytes(edit))
        issue = next(i for i in result["issues"] if i["code"] == "unmapped_posting")
        reported = list(zip(issue["values"], issue["sources"]))
        expected = []
        for resident in [resident for sheet in result["annual_sheets"] for resident in sheet["residents"]]:
            for posting in resident["postings"]:
                pair = (posting["value"], posting["source"])
                if posting["value"] and posting["value"].strip().casefold() != "loa" and pair not in expected:
                    expected.append(pair)
        self.assertEqual(reported, expected)
        self.assertFalse(any(value.strip().casefold() == "loa" for value in issue["values"]))
        self.assertEqual(result["histories"][0]["residents"][0]["postings"][1]["value"], " loa ")
        self.assertEqual(issue["severity"], "info")

    def test_months_history_and_raw_text_remain_separate(self):
        r = parse_workbook(workbook_bytes())
        self.assertEqual([s["year"] for s in r["available_years"]], [2026, 2027])
        self.assertEqual(r["months"][0]["month"], "2027-07")
        self.assertEqual(r["months"][-1]["month"], "2028-06")
        self.assertEqual(r["months"][0]["date_range_text"], "7 Jul - 5 Aug (original display text)")
        self.assertEqual(r["residents"][0]["residency_year"], "R2,R3")
        p = r["residents"][0]["postings"]
        self.assertEqual(r["residents"][0]["remarks"], "Preserved merged header remark")
        self.assertEqual(p[0]["value"], "LOA")
        self.assertEqual(p[1]["source"], p[2]["source"])
        self.assertEqual(r["histories"][0]["year"], 2026)
        self.assertNotIn("completed", r["histories"][0]["residents"][0])
        self.assertEqual(r["requests"][0]["period"], "Either Jul or Oct")
        self.assertEqual(r["postings"]["core"][0]["duration_months"], "3")
        self.assertEqual(r["postings"]["rows"][1]["cells"]["A"], "Raw elective note")
        self.assertEqual(r["postings"]["core"][1]["posting"], "Standalone posting")

    def test_elective_catalogue_preserves_labels_notes_sources_and_separate_years(self):
        def edit(w):
            sheet = w["Postings"]
            sheet["B1"] = "R5 Electives"
            cells = {
                "A2": "Sites/Department", "A3": "SITEA (3 months duration)",
                "A4": "  - First Department  ", "A5": "(local note)",
                "A6": "- Second Department", "A7": "SITEB", "A8": "- Third Department",
                "B2": "Sites/Department", "B3": "SITEA (all required 6 months duration)",
                "B4": "- First Department (6 months)", "B5": "  (continuation verbatim)  ",
                "B6": "(second continuation)", "B7": "- Second Department", "B8": "SITEB",
                "B9": "(orphan note)", "B10": "- Combined Department", "B11": "(3 months- pairing note)",
            }
            for address, value in cells.items():
                sheet[address] = value
            w["Jul 2027 - Jun 2028"]["J3"] = "First Department (6 months)"
        result = parse_workbook(workbook_bytes(edit))
        electives = result["postings"]["electives"]
        self.assertEqual([(e["residency_year"], e["institution"], e["elective"]) for e in electives], [
            ("R2", "SITEA", "First Department"), ("R2", "SITEA", "Second Department"),
            ("R2", "SITEB", "Third Department"), ("R5", "SITEA", "First Department (6 months)"),
            ("R5", "SITEA", "Second Department"), ("R5", "SITEB", "Combined Department")])
        ref = lambda row, column: {"sheet": "Postings", "row": row, "column": column}
        self.assertEqual(electives[0]["source"], ref(4, "A"))
        self.assertEqual(electives[0]["institution_source"], ref(3, "A"))
        self.assertEqual(electives[0]["residency_year_source"], ref(1, "A"))
        self.assertEqual(electives[0]["remarks"], [
            {"text": "(3 months duration)", "source": ref(3, "A")},
            {"text": "(local note)", "source": ref(5, "A")}])
        self.assertEqual(electives[1]["remarks"], electives[0]["remarks"][:1])
        self.assertEqual(electives[2]["remarks"], [])
        self.assertEqual(electives[3]["remarks"], [
            {"text": "(all required 6 months duration)", "source": ref(3, "B")},
            {"text": "  (continuation verbatim)  ", "source": ref(5, "B")},
            {"text": "(second continuation)", "source": ref(6, "B")}])
        self.assertEqual(electives[4]["remarks"], electives[3]["remarks"][:1])
        self.assertEqual(electives[5]["remarks"], [{"text": "(3 months- pairing note)", "source": ref(11, "B")}])
        self.assertEqual(next(r for r in result["postings"]["rows"] if r["source"]["row"] == 4)["cells"]["A"], "  - First Department  ")
        self.assertEqual(result["postings"]["core"][0]["posting"], "Core example")
        issue = next(i for i in result["issues"] if i["code"] == "unmapped_posting")
        self.assertIn("First Department (6 months)", issue["values"])
        self.assertNotIn("duration_months", electives[3])

    def test_elective_columns_are_optional_and_follow_headers(self):
        def edit(w):
            sheet = w["Postings"]
            sheet["A1"] = None
            sheet["B1"] = "R5 Electives"
            sheet["B2"] = "- Orphan elective"
            sheet["B3"] = "SITEA"
            sheet["B4"] = "\u2022 Department"
            sheet["B5"] = "Unrecognised heading"
            sheet["B6"] = "- Must remain raw"
            sheet["B7"] = "(Must not attach to Department)"
        result = parse_workbook(workbook_bytes(edit))
        self.assertEqual(len(result["postings"]["electives"]), 1)
        self.assertEqual(result["postings"]["electives"][0]["residency_year"], "R5")
        self.assertEqual(result["postings"]["electives"][0]["source"]["column"], "B")
        self.assertEqual(result["postings"]["electives"][0]["remarks"], [])
        result = parse_workbook(workbook_bytes(lambda w: setattr(w["Postings"]["A1"], "value", None)))
        self.assertEqual(result["postings"]["electives"], [])
        self.assertEqual(len(result["postings"]["core"]), 2)

    def test_missing_target_and_corrupt_workbooks(self):
        with self.assertRaisesRegex(WorkbookError, "No July"):
            parse_workbook(workbook_bytes(), 2030)
        with self.assertRaisesRegex(WorkbookError, "valid, unencrypted"):
            parse_workbook(b"not a workbook")
        stream = BytesIO()
        with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
            archive.writestr("large.xml", b"x" * (51 * 1024 * 1024))
        with self.assertRaisesRegex(WorkbookError, "expanded"):
            parse_workbook(stream.getvalue())

    def test_api_upload_validation(self):
        with TestClient(app) as client:
            good = client.post("/api/import", files={"file": ("example.xlsx", workbook_bytes())})
            self.assertEqual(good.status_code, 200, good.text)
            self.assertEqual(good.json()["target_year"], 2027)
            for name, content in (("wrong.csv", b"text"), ("broken.xlsx", b"bad")):
                self.assertEqual(client.post("/api/import", files={"file": (name, content)}).status_code, 400)
            self.assertEqual(client.post("/api/import", files={"file": ("large.xlsx", b"x" * (MAX_UPLOAD_BYTES + 1))}).status_code, 413)
            self.assertEqual(client.post("/api/import", data={"target_year": "bad"}, files={"file": ("example.xlsx", workbook_bytes())}).status_code, 422)


class IncomingIntakeTests(unittest.TestCase):
    def parse(self, rows, history_placeholder=False):
        def edit(w):
            sheet = w["Jul 2027 - Jun 2028"]
            sheet.title = "Jul planning"  # The month headings, not the title, define intake.
            sheet["C2"] = "Residency Intake"
            for row, (name, mcr, year, intake) in enumerate(rows, 3):
                for column, value in zip((4, 5, 6, 3), (name, mcr, year, intake)):
                    sheet.cell(row, column).value = value
            if history_placeholder:
                history = w["Jul 2026 - Jun 2027"]
                history["A3"] = "Residency Intake"
                history["A4"], history["B4"], history["C4"], history["D4"] = 2026, "Resident 1", None, "R1"
        return parse_workbook(workbook_bytes(edit))

    def test_named_residents_and_existing_placeholders_share_the_intake_count(self):
        for named in (0, 1, 2):
            with self.subTest(named=named):
                rows = [(f"Named {n}", f"M{n}", "R1", 2027) for n in range(named)]
                rows += [(f"Resident {n}", None, " r1 ", " 2027 ") for n in range(1, 25 - named)]
                result = self.parse(rows, history_placeholder=True)
                summary = result["incoming_intake"]
                self.assertEqual((summary["year"], summary["total_count"], summary["named_count"], summary["placeholder_count"]),
                                 (2027, 24, named, 24 - named))
                self.assertEqual(len(summary["resident_sources"]), 24)
                self.assertFalse(any(i["code"] == "missing_mcr" for i in result["issues"]))
                placeholders = [r for r in result["residents"] if r["is_intake_placeholder"]]
                self.assertTrue(all(r["match_status"] == "unmatched" and r["matched_resident_source"] is None for r in placeholders))
                history = result["histories"][0]["residents"][0]
                self.assertTrue(history["is_intake_placeholder"])
                self.assertEqual(history["match_status"], "unmatched")
                self.assertIsNone(history["matched_resident_source"])

    def test_continuing_mixed_and_unclear_intakes_are_not_assumed_incoming(self):
        rows = [("Named", "M1", "R1", 2027), ("Continuing", "M2", "R1", 2026),
                ("Mixed", "M3", "R1,R2", 2027), ("Missing", "M4", "R1", None),
                ("Conflicting", "M5", "R1", "2026/2027"), ("Malformed", "M6", "R1", "AY2027"), ("Future", "M7", "R1", 2028)]
        result = self.parse(rows)
        self.assertEqual(result["incoming_intake"]["total_count"], 1)
        unclear = [i for i in result["issues"] if i["code"] == "unclear_intake"]
        self.assertEqual([i["source"]["row"] for i in unclear], [6, 7, 8, 9])
        self.assertEqual(len(result["residents"]), len(rows))

    def test_ordinary_missing_mcr_and_unrecognized_placeholders_remain_unsafe(self):
        rows = [("Named", None, "R1", 2027), ("Resident 0", None, "R1", 2027),
                ("Resident 1", None, "R1,R2", 2027), ("Resident 2", None, "R1", None),
                ("Resident 3", None, "R1", 2026)]
        result = self.parse(rows)
        self.assertEqual(len([i for i in result["issues"] if i["code"] == "missing_mcr"]), 5)
        self.assertTrue(all(not r["is_intake_placeholder"] and r["match_status"] != "matched" for r in result["residents"]))

    def test_duplicates_and_excess_are_reported_without_removing_rows(self):
        rows = [(f"Resident {n}", None, "R1", 2027) for n in range(1, 25)]
        rows += [("Named", "M1", "R1", 2027)]
        boundary = self.parse(rows)
        self.assertEqual(boundary["incoming_intake"]["total_count"], 25)
        self.assertIn("excess_intake", {i["code"] for i in boundary["issues"]})
        rows += [(" resident  1 ", None, "R1", 2027),
                 ("Named", "M1", "R1", 2027), ("Resident 25", None, "R1", 2027)]
        result = self.parse(rows)
        self.assertEqual(result["incoming_intake"]["placeholder_count"], 26)
        self.assertEqual(result["incoming_intake"]["total_count"], 28)
        self.assertEqual(len(result["residents"]), 28)
        self.assertTrue({"duplicate_intake_placeholder", "duplicate_mcr", "excess_intake"} <= {i["code"] for i in result["issues"]})
        duplicate = next(i for i in result["issues"] if i["code"] == "duplicate_intake_placeholder")
        self.assertEqual([r["source"]["row"] for r in duplicate["records"]], [3, 28])
        self.assertTrue(all(r["match_status"] == "ambiguous" for r in result["residents"] if r["mcr"] == "M1"))


class HistoricalPostingMatchTests(unittest.TestCase):
    def catalogue(self):
        core = [{"posting": label, "residency_year": year,
                 "source": {"sheet": "Catalogue", "row": row}}
                for row, (label, year) in enumerate([
                    ("NUH Inpatient Psychiatry", "R1"),
                    ("IMH Addiction Medicine", "R2"),
                    ("IMH Forensic Psychiatry", "R4"),
                    ("SGH Neurology", "R1")], 10)]
        electives = [{"institution": institution, "elective": label, "residency_year": year,
                      "source": {"sheet": "Catalogue", "row": row, "column": "B"}}
                     for row, (institution, label, year) in enumerate([
                         ("NUH", "Inpatient Psychiatry", "R2"),
                         ("IMH", "Addiction Medicine", "R2"),
                         ("IMH", "Forensic Psychiatry", "R5"),
                         ("IMH", "Adult Neurodevelopmental Disorders Service (ANDS)", "R2"),
                         ("IMH", "Adult Neurodevelopmental Disorders Service (ANDS)", "R5"),
                         ("CGH", "Inpatient Psychiatry", "R2"),
                         ("SGH", "Eating disorder", "R2"),
                         ("SGH", "Psycho-oncology cum Palliative", "R2"),
                         ("NUH", "Women\ufffds Emotional Health Service", "R2")], 20)]
        return posting_catalogue({"core": core, "electives": electives})

    def match(self, value, year="R2", catalogue=None, status="posting"):
        posting = {"value": value, "status": status,
                   "source": {"sheet": "Anonymous history", "row": 91, "column": "J"}}
        original = deepcopy(posting)
        result = match_posting(posting, year, self.catalogue() if catalogue is None else catalogue)
        self.assertEqual(posting, original)
        return result

    def test_elective_marker_variants_restrict_candidates_and_keep_catalogue_refs(self):
        for label in ("NUH Inpatient Psychiatry(Elective)",
                      " nuh  Inpatient Psychiatry ( eLeCtIvE ) "):
            with self.subTest(label=label):
                result = self.match(label)
                self.assertEqual(result["status"], "matched")
                self.assertEqual(len(result["candidates"]), 1)
                candidate = result["candidates"][0]
                self.assertEqual(candidate["category"], "elective")
                self.assertEqual(candidate["source"], {"sheet": "Catalogue", "row": 20, "column": "B"})
        self.assertEqual(self.match("SGH Neurology (Elective)", "R1")["status"], "unmatched")

    def test_unique_core_precedence_resolves_same_and_other_year_elective_alternatives(self):
        for label, year in (("NUH Inpatient Psychiatry", "R1"),
                            ("IMH Addiction Medicine", "R2"),
                            ("IMH Forensic Psychiatry", "R4")):
            with self.subTest(label=label):
                result = self.match(label, year)
                self.assertEqual(result["candidates"][0]["category"], "core")
                self.assertEqual(len(result["candidates"]), 2)
                self.assertEqual(result["status"], "matched")
                self.assertEqual(result["selected_candidate"]["category"], "core")
                self.assertIn("catalogue_alternatives", result["reasons"])
                self.assertNotIn("core_elective_ambiguity", result["reasons"])

    def test_year_context_ranks_but_never_drops_earlier_requirements(self):
        label = "IMH Adult Neurodevelopmental Disorders Service (ANDS) (Elective)"
        for year, first, reason in (("R3", "R2", "earlier_year_fallback"),
                                    ("R5", "R5", "catalogue_alternatives"),
                                    ("R2,R5", "R2", "mixed_recorded_years")):
            with self.subTest(year=year):
                result = self.match(label, year)
                self.assertEqual(result["status"], "matched" if year in {"R3", "R5"} else "ambiguous")
                self.assertEqual(result["candidates"][0]["residency_year"], first)
                self.assertEqual({c["residency_year"] for c in result["candidates"]}, {"R2", "R5"})
                self.assertIn(reason, result["reasons"])
        result = self.match("CGH Inpatient Psychiatry (Elective)", "R3")
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["selected_candidate"]["residency_year"], "R2")
        self.assertEqual(result["selected_candidate"]["year_context"], "earlier_fallback_year")
        self.assertEqual(self.match("SGH Neurology", "R1,R2")["status"], "matched")
        self.assertNotIn("mixed_recorded_years", self.match("SGH Neurology", "R1,R2")["reasons"])

    def test_remediation_recognizes_label_but_requires_separate_credit_review(self):
        result = self.match(" SGH Neurology (Remediation) ", "R1")
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("remediation_credit_review", result["reasons"])
        self.assertEqual(result["candidates"][0]["label"], "SGH Neurology")

    def test_no_builtin_aliases_and_case_whitespace_normalization(self):
        self.assertEqual(self.match("Unreviewed historical wording (Elective)", "R3")["status"], "unmatched")
        for label in ("SGH Eating Disorder (Elective)", "SGH Psycho-Oncology cum Palliative(Elective)"):
            self.assertEqual(self.match(label)["status"], "matched")
        for label in ("Unknown", "TTSH Psychiatry(Elective)",
                      "NUH Consultation Liaison Psychiatry(Elective)",
                      "SKH Consultation Liaison Psychiatry (Elective)",
                      "NUH Women's Emotional Health Service (Elective)"):
            with self.subTest(label=label):
                self.assertEqual(self.match(label)["status"], "unmatched")
        self.assertEqual(self.match("NUH Women\ufffds Emotional Health Service (Elective)")["candidates"][0]["label"],
                         "NUH Women\ufffds Emotional Health Service")

    def test_unknown_year_and_missing_alias_target_need_review(self):
        result = self.match("SGH Neurology", "Unknown year")
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("recorded_year_unknown", result["reasons"])
        self.assertEqual(result["candidates"][0]["year_context"], "unknown")
        result = self.match("Unreviewed historical wording (Elective)", catalogue=[])
        self.assertEqual(result["status"], "unmatched")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(self.match("SGH Neurology (Unreviewed qualifier)", "R1")["status"], "unmatched")

    def test_optional_catalogue_and_non_postings(self):
        catalogue = posting_catalogue({"core": [{"posting": "Example", "source": {"sheet": "Ref", "row": 2}}]})
        result = self.match("Example", catalogue=catalogue)
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("catalogue_year_unknown", result["reasons"])
        self.assertEqual(self.match("Example (Elective)", catalogue=catalogue)["status"], "unmatched")
        self.assertEqual(self.match("Example", catalogue=[])["status"], "unmatched")
        for value, status in (("LOA", "loa"), (None, "blank")):
            self.assertEqual(self.match(value, status=status), {"status": "not_applicable", "reasons": [], "candidates": []})

    def test_import_adds_matches_without_rewriting_history_or_current_year(self):
        def edit(w):
            w["Postings"]["A2"] = "CGH"
            w["Postings"]["A3"] = "- Inpatient Psychiatry"
            w["Jul 2026 - Jun 2027"]["D4"] = "R3"
            w["Jul 2026 - Jun 2027"]["F4"] = " CGH Inpatient Psychiatry (Elective) "
            w["Jul 2027 - Jun 2028"]["F3"] = "R3"
        result = parse_workbook(workbook_bytes(edit))
        history = result["histories"][0]["residents"][0]
        self.assertEqual(history["residency_year"], "R3")
        self.assertEqual(result["residents"][0]["residency_year"], "R3")
        self.assertEqual(history["match_status"], "matched")
        posting = history["postings"][1]
        self.assertEqual(posting["value"], " CGH Inpatient Psychiatry (Elective) ")
        self.assertEqual(posting["status"], "posting")
        self.assertEqual(posting["source"], {"sheet": "Jul 2026 - Jun 2027", "row": 4, "column": "F"})
        self.assertEqual(posting["catalogue_match"]["status"], "matched")
        self.assertEqual(posting["catalogue_match"]["candidates"][0]["residency_year"], "R2")
        self.assertNotIn("completed", history)
        self.assertNotIn(posting["value"], next(i for i in result["issues"] if i["code"] == "unmapped_posting")["values"])


if __name__ == "__main__":
    unittest.main()
