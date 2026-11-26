from collections import Counter
from copy import deepcopy
import unittest

from scheduler import draft_schedule
from scheduler_inputs import prepare_scheduler_inputs
from tests.test_r1_solver import STORE
from tests.test_workbook_import import structured_workbook_bytes
from workbook_import import parse_workbook
from tests.test_r4_rules import r4_book
from tests.test_requirement_ledger import resident


def r5_book():
    book = r4_book()
    for sheet in book["annual_sheets"]:
        for past in sheet["residents"]:
            if past is book["residents"][0]:
                continue
            for month in past["postings"]:
                month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
    labels = ["NUH Inpatient Psychiatry"] * 3 + ["SGH Consultation Liaison Psychiatry"] * 3 + ["IMH Emergency Psychiatry"] * 3 + ["IMH Forensic Psychiatry"] * 3
    book["annual_sheets"].append({"residents": [resident(
        [(f"{2026 + (i + 6) // 12}-{(i + 6) % 12 + 1:02d}", label) for i, label in enumerate(labels)], "R4", "R4 history")]})
    for name, sites in (("Geriatric Psychiatry", ("IMH", "CGH", "NUH")),
                        ("Child & Adolescent Psychiatry", ("IMH", "NUH", "KKH"))):
        for site in sites:
            book["postings"]["core"].append({"residency_year": "R5", "posting": f"{site} {name}",
                "duration_months": "3", "source": {"sheet": "Postings", "row": 600 + len(book["postings"]["core"])}})
    book["postings"]["electives"].append({"residency_year": "R5", "institution": "IMH", "elective": "Forensic Psychiatry", "remarks": [],
        "source": {"sheet": "Postings", "row": 500}})
    book["residents"][0]["residency_year"] = "R5"
    return book


class R5Tests(unittest.TestCase):
    def test_training_progresses_at_every_year_boundary_with_months_left(self):
        for recorded, year_counts, carry in (
                ("R1", {"R1": 2, "R2": 10}, 2),
                ("R2", {"R2": 3, "R3": 9}, 3),
                ("R3", {"R3": 2, "R4": 10}, 2),
                ("R4", {"R3": 2, "R4": 6, "R5": 4}, 8)):
            with self.subTest(recorded=recorded):
                book = r5_book()
                roster = book["residents"][0]
                roster["residency_year"] = recorded
                histories = {person["residency_year"]: person for sheet in book["annual_sheets"]
                             for person in sheet["residents"] if person is not roster}
                latest = int(recorded[1])
                for sheet in book["annual_sheets"]:
                    sheet["residents"] = [person for person in sheet["residents"]
                                          if person is roster or int(person["residency_year"][1]) <= latest]
                histories[recorded]["postings"] = histories[recorded]["postings"][:{1: 10, 2: 9, 3: 10, 4: 6}[latest]]
                if recorded == "R4":
                    histories["R3"]["postings"] = histories["R3"]["postings"][:10]
                    book["requests"] = [{"posting_request": "IMH Forensic Psychiatry (Elective)",
                                         "period": None, "matched_resident_source": roster["source"]}]
                before = deepcopy(book)
                result = draft_schedule(book, STORE)
                self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
                person, = result["residents"]
                expected = [year for year, count in year_counts.items() for _ in range(count)]
                self.assertEqual([m["target"]["residency_year"] for m in person["months"]], expected)
                self.assertEqual(person["recorded_year"], recorded)
                self.assertEqual(person["projected_year"], f"{recorded},R{latest + 1}")
                self.assertEqual(sum(c["months"] for c in person["carryforward"]), carry)
                if recorded == "R4":
                    self.assertEqual(person["requests"][0]["status"], "met")
                self.assertEqual(book, before)

    def test_loa_can_prevent_entry_into_next_year_without_validating_its_catalogue(self):
        book = r5_book()
        roster = book["residents"][0]
        roster["residency_year"] = "R2"
        book["annual_sheets"] = [sheet for sheet in book["annual_sheets"]
                                 if sheet["residents"][0]["residency_year"] in {"R1", "R2"}]
        r2_history = book["annual_sheets"][-1]["residents"][0]
        r2_history["postings"] = r2_history["postings"][:9]
        for month in roster["postings"][3:]:
            month.update(status="loa", value="LOA")
        catalogue = book["postings"]["core"]
        book["postings"]["core"] = [row for row in catalogue if row["residency_year"] != "R3"]
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        person, = result["residents"]
        self.assertEqual([m["target"]["residency_year"] for m in person["months"][:3]], ["R2"] * 3)
        self.assertTrue(all(m["status"] == "loa" for m in person["months"][3:]))
        self.assertEqual(person["projected_year"], "R2")
        self.assertEqual(person["carryforward"], [])

        book["postings"]["core"] = catalogue
        roster["postings"][3].update(status="blank", value=None)
        book["requests"] = [{"posting_request": "NUH Continuity Clinic", "period": None,
                             "matched_resident_source": roster["source"]}]
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        person, = result["residents"]
        self.assertEqual(person["months"][3]["label"], "NUH Continuity Clinic")
        self.assertEqual(person["requests"][0]["status"], "met")
        self.assertEqual(person["projected_year"], "R2,R3")
        carry, = person["carryforward"]
        self.assertEqual((carry["requirement_id"], carry["institution"], carry["months"]), ("r3.continuity_clinic", "NUH", 11))

    def test_progression_skips_completed_years_and_enforces_projected_imh_exclusion(self):
        book = r5_book()
        roster = book["residents"][0]
        roster["residency_year"] = "R1"
        book["annual_sheets"].pop()  # R4 has no historical credit.
        book["annual_sheets"][0]["residents"][0]["postings"].pop()
        book["requests"] = [{"posting_request": "IMH Inpatient Psychiatry", "period": None,
                             "matched_resident_source": roster["source"]}]
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        person, = result["residents"]
        self.assertEqual(person["months"][0]["label"], "IMH Inpatient Psychiatry")
        self.assertTrue(all(m["target"]["residency_year"] == "R4" for m in person["months"][1:]))
        self.assertNotIn("IMH Inpatient Psychiatry", [m["label"] for m in person["months"][1:]])
        self.assertEqual(person["projected_year"], "R1,R4")
        self.assertEqual(person["requests"][0]["status"], "not_met")
        self.assertFalse(person["cluster_coverage"]["projected"]["missing"])

    def test_full_r5_with_workbook_catalogue(self):
        book = r5_book()
        before = deepcopy(book)
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        person = result["residents"][0]
        self.assertEqual(Counter(m["target"]["requirement_id"] for m in person["months"]),
                         {"r5.geriatric_psychiatry": 3, "r5.child_adolescent_psychiatry": 3, "r5.elective": 6})
        self.assertTrue(all(m["target"]["source"]["sheet"] == "Postings" for m in person["months"]))
        for requirement in {m["target"]["requirement_id"] for m in person["months"]}:
            indices = [i for i, m in enumerate(person["months"]) if m["target"]["requirement_id"] == requirement]
            self.assertEqual(indices, list(range(indices[0], indices[-1] + 1)))
            self.assertEqual(len({person["months"][i]["label"] for i in indices}), 1)
        self.assertEqual(book, before)

    def test_added_geriatric_sites_count_history_and_schedule_remaining_months(self):
        for site in ("TTSH", "SKH"):
            with self.subTest(site=site):
                book = r5_book()
                for sheet in book["annual_sheets"]:
                    for past in sheet["residents"]:
                        if past is not book["residents"][0]:
                            for month in past["postings"]:
                                month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
                label = f"{site} Geriatric Psychiatry"
                book["postings"]["core"].append({"residency_year": "R5", "posting": label,
                    "duration_months": "3", "max": "1", "source": {"sheet": "Postings", "row": 700}})
                book["annual_sheets"].append({"residents": [resident(
                    [("2027-06", label)], "R5", "R5 history")]})
                result = draft_schedule(book, STORE)
                self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
                self.assertEqual([m["label"] for m in result["residents"][0]["months"][:2]], [label] * 2)
                book["postings"]["core"].pop()
                prepared = prepare_scheduler_inputs(book, STORE)
                requirement = next(r for r in prepared["residents"][0]["requirements"]
                                   if r["requirement_id"] == "r5.geriatric_psychiatry")
                self.assertEqual(requirement["expected_months"], 0)
                self.assertFalse(prepared["residents"][0]["input_ready"])

    def test_explicit_core_capacity_and_history_credit(self):
        book = r5_book()
        book["postings"]["core"] = [o for o in book["postings"]["core"] if o["residency_year"] != "R5"
                                    or "Geriatric Psychiatry" not in o["posting"] or o["posting"] == "NUH Geriatric Psychiatry"]
        next(o for o in book["postings"]["core"] if o["residency_year"] == "R5" and o["posting"] == "NUH Geriatric Psychiatry")["max"] = "1"
        options = prepare_scheduler_inputs(book, STORE)["catalogue_options"]
        geri = [o for o in options if o["requirement_id"] == "r5.geriatric_psychiatry"]
        self.assertEqual([(o["institution"], o["capacity"]) for o in geri], [("NUH", 1)])
        # Recognised R5 core history uses the explicit workbook catalogue.
        for sheet in book["annual_sheets"]:
            for past in sheet["residents"]:
                if past is book["residents"][0]:
                    continue
                for month in past["postings"]:
                    month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
        book["annual_sheets"].append({"residents": [resident([("2027-06", "NUH Geriatric Psychiatry")], "R5", "R5 history")]})
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        self.assertEqual([m["label"] for m in result["residents"][0]["months"][:2]], ["NUH Geriatric Psychiatry"] * 2)
        next(o for o in book["postings"]["core"] if o["residency_year"] == "R5" and o["posting"] == "NUH Geriatric Psychiatry")["max"] = "0"
        overflow = draft_schedule(book, STORE)
        self.assertEqual(overflow["status"], "optimal")
        self.assertEqual(overflow["soft_results"]["capacity_overflow"], 2)
        self.assertEqual([m["label"] for m in overflow["residents"][0]["months"][:2]], ["NUH Geriatric Psychiatry"] * 2)
        self.assertEqual(len(overflow["capacity_overflows"]), 2)

    def test_mixed_r4_r5_and_loa_carryforward(self):
        book = r5_book()
        for month in book["annual_sheets"][-1]["residents"][0]["postings"][-3:]:
            month.update(status="loa", value="LOA")
        book["residents"][0]["residency_year"] = "R4,R5"
        book["residents"][0]["postings"][1].update(status="loa", value="LOA")
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        person = result["residents"][0]
        self.assertEqual([person["months"][i]["target"]["requirement_id"] for i in (0, 2, 3)], ["r4.forensic_psychiatry"] * 3)
        self.assertEqual(sum(item["months"] for item in person["carryforward"]), 4)

    def test_unfinished_r2_precedes_r5_even_after_later_history(self):
        book = r5_book()
        r2 = next(p for sheet in book["annual_sheets"] for p in sheet["residents"]
                  if p.get("residency_year") == "R2")
        for month in r2["postings"][:3]:
            month.update(status="loa", value="LOA")
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        months = result["residents"][0]["months"]
        self.assertTrue(all(m["target"]["requirement_id"] == "r2.elective" for m in months[:3]))
        self.assertTrue(all(m["target"]["requirement_id"].startswith("r5.") for m in months[3:]))
        self.assertEqual(sum(item["months"] for item in result["residents"][0]["carryforward"]), 3)

    def test_duration_aware_balance_and_weighted_sites(self):
        book = r5_book()
        for sheet in book["annual_sheets"]:
            for original in list(sheet["residents"]):
                for i in range(1, 4):
                    duplicate = deepcopy(original)
                    duplicate.update(name=f"R5 Resident {i}", mcr=f"R5-{i}", source={**original["source"], "row": i + 3})
                    for month in duplicate["postings"]:
                        month["source"]["row"] = i + 3
                    sheet["residents"].append(duplicate)
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "optimal", result["blockers"])
        people = result["residents"]
        for month in range(12):
            counts = Counter(p["months"][month]["target"]["requirement_id"] for p in people)
            self.assertEqual(counts, {"r5.geriatric_psychiatry": 1, "r5.child_adolescent_psychiatry": 1, "r5.elective": 2})
        geri = Counter(next(m["target"]["institution"] for m in p["months"]
                            if m["target"]["requirement_id"] == "r5.geriatric_psychiatry") for p in people)
        self.assertEqual(geri, {"IMH": 2, "CGH": 1, "NUH": 1})
        self.assertEqual(result["soft_results"]["r5_allocation_deviation"], 0)
        # Once the elective is completed, only the remaining two cores balance.
        for sheet in book["annual_sheets"]:
            for past in sheet["residents"]:
                if any(past is person for person in book["residents"]):
                    continue
                for month in past["postings"]:
                    month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
        histories = []
        for i, person in enumerate(book["residents"]):
            past = resident([(f"2027-{m:02d}", "IMH Forensic Psychiatry (Elective)") for m in range(1, 7)], "R5", "R5 elective", i + 3)
            past.update(name=person["name"], mcr=person["mcr"])
            histories.append(past)
        book["annual_sheets"].append({"residents": histories})
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "optimal", result["blockers"])
        for month in range(6):
            counts = Counter(p["months"][month]["target"]["requirement_id"] for p in result["residents"])
            self.assertEqual(counts, {"r5.geriatric_psychiatry": 2, "r5.child_adolescent_psychiatry": 2})

    def test_r5_continues_with_historical_cluster_gap_after_all_r1_r4_training(self):
        book = r5_book()
        r1_history = book["annual_sheets"][0]["residents"][0]["postings"]
        for month in r1_history[:6]:
            month["value"] = "NUH Medicine & Neurology"
        r4_history = book["annual_sheets"][-1]["residents"][0]["postings"]
        for month in r4_history[3:6]:
            month["value"] = "TTSH Consultation Liaison Psychiatry"
        # An R5 posting in SHS is available and assigned, but cannot fill the gap.
        book["postings"]["core"] = [o for o in book["postings"]["core"] if o["residency_year"] != "R5"
                                    or "Geriatric Psychiatry" not in o["posting"] or o["posting"] == "CGH Geriatric Psychiatry"]

        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        self.assertEqual(result["skipped_residents"], [])
        person = result["residents"][0]
        self.assertTrue(all(m["target"]["residency_year"] == "R5" for m in person["months"]))
        self.assertIn("CGH Geriatric Psychiatry", [m["label"] for m in person["months"]])
        self.assertEqual(person["cluster_coverage"]["historical"]["missing"], ["SHS"])
        self.assertEqual(person["cluster_coverage"]["projected"]["missing"], ["SHS"])
        [warning] = result["historical_cluster_warnings"]
        self.assertEqual(warning["source"], person["source"])
        self.assertEqual(warning["reasons"], [{"code": "historical_cluster_gap", "source": person["source"], "clusters": ["SHS"]}])

        early = deepcopy(book)
        imported = parse_workbook(structured_workbook_bytes())
        early["postings"]["electives"].extend(row for row in imported["postings"]["electives"]
                                                if row.get("additional_requirement"))
        early["postings"]["core"] = [o for o in early["postings"]["core"] if o["residency_year"] != "R5"
                                     or not o["posting"].endswith("Child & Adolescent Psychiatry")]
        shortened = draft_schedule(early, STORE)
        self.assertIn(shortened["status"], {"optimal", "feasible"}, shortened["blockers"])
        self.assertTrue(all(m["status"] == "posting" for m in shortened["residents"][0]["months"]))
        self.assertEqual(shortened["historical_cluster_warnings"], result["historical_cluster_warnings"])

        # The same R5 record label and completed R4 blocks don't exempt someone
        # who still has R3 training and can visit SHS during those postings.
        del book["annual_sheets"][-2]
        unfinished = draft_schedule(book, STORE)
        self.assertIn(unfinished["status"], {"optimal", "feasible"}, unfinished["blockers"])
        self.assertFalse(unfinished.get("historical_cluster_warnings"))
        person = unfinished["residents"][0]
        self.assertTrue(all(m["target"]["residency_year"] == "R3" for m in person["months"]))
        self.assertEqual(person["cluster_coverage"]["projected"]["missing"], [])

    def test_r5_cannot_satisfy_r4_cluster_deadline(self):
        book = r5_book()
        history = book["annual_sheets"][-1]["residents"][0]["postings"]
        for month in history:
            if month["value"] in {"NUH Inpatient Psychiatry", "SGH Consultation Liaison Psychiatry"}:
                month["value"] = "TTSH " + month["value"].split(" ", 1)[1]
        for month in history[-3:]:
            month.update(status="loa", value="LOA")
        book["residents"][0]["residency_year"] = "R4,R5"
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "infeasible")

    def test_unsupported_electives_are_excluded_without_blocking_standard_choices(self):
        book = r5_book()
        book["postings"]["electives"].append({"residency_year": "R5", "institution": "SGH", "elective": "Psychogeriatrics Psychiatry",
            "remarks": [{"text": "(which will meet the core 3months R5 Psychogeriatrics requirements)"}], "source": {"sheet": "Postings", "row": 501}})
        result = draft_schedule(book, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        self.assertFalse(any(m["label"] == "SGH Psychogeriatrics Psychiatry" for m in result["residents"][0]["months"]))
        self.assertTrue(any("unsupported remarks" in item for item in result["limitations"]))
        # A partial unsupported elective cannot be switched to the standard one.
        for sheet in book["annual_sheets"]:
            for past in sheet["residents"]:
                if past is book["residents"][0]:
                    continue
                for month in past["postings"]:
                    month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
        book["annual_sheets"].append({"residents": [resident([("2027-06", "SGH Psychogeriatrics Psychiatry (Elective)")], "R5", "Partial")]})
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("missing_r5_catalogue_option", [r["code"] for r in result["skipped_residents"][0]["reasons"]])

    def test_mixed_credit_and_separate_core_requests_fill_twelve_months(self):
        book = r5_book()
        imports = parse_workbook(structured_workbook_bytes())
        credit = next(row for row in imports["postings"]["electives"] if row.get("additional_requirement"))
        book["postings"]["electives"].append(credit)
        roster = book["residents"][0]
        label = "IMH Child and EPIP"
        book["requests"] = [
            {"posting_request": posting, "period": period, "matched_resident_source": roster["source"]}
            for posting, period in (("KKH Child & Adolescent Psychiatry (Core)", "Jul - Sep 2027"),
                                    (f"{label} (Elective)", "Jan - Jun 2028"))]
        draft = draft_schedule(book, STORE)
        self.assertIn(draft["status"], {"optimal", "feasible"}, draft["blockers"])
        person, = draft["residents"]
        self.assertEqual([row["status"] for row in person["requests"]], ["met", "met"])
        self.assertEqual([m["label"] for m in person["months"][6:]], [label] * 6)
        self.assertTrue(all(m["status"] == "posting" for m in person["months"]))
        self.assertFalse(person["carryforward"])

        combined = {"residency_year": "R5", "posting": "CGH Child and Geriatric Psychiatry",
                    "duration_months": "6", "source": {"sheet": "Postings", "row": 900}}
        book["postings"]["core"].append(combined)
        book["requests"][0].update(posting_request=combined["posting"], period="Jul - Dec 2027")
        draft = draft_schedule(book, STORE)
        self.assertIn(draft["status"], {"optimal", "feasible"}, draft["blockers"])
        person, = draft["residents"]
        self.assertEqual([row["status"] for row in person["requests"]], ["met", "met"])
        self.assertEqual([m["label"] for m in person["months"]], [combined["posting"]] * 6 + [label] * 6)
        book["postings"]["core"].remove(combined)

        # The mixed posting can replace the separate Child core with a regular
        # three-month elective making up the remainder. Capacity counts it once.
        book["postings"]["core"] = [o for o in book["postings"]["core"] if o["residency_year"] != "R5"
                                    or not o["posting"].endswith("Child & Adolescent Psychiatry")]
        credit["max"] = "0"
        book["requests"] = book["requests"][1:]
        book["requests"][0]["period"] = "Jul - Dec 2027"
        book["requests"].append({"posting_request": "IMH Forensic Psychiatry (Elective)", "period": "Jan - Mar 2028",
                                 "matched_resident_source": roster["source"]})
        draft = draft_schedule(book, STORE)
        self.assertIn(draft["status"], {"optimal", "feasible"}, draft["blockers"])
        person, = draft["residents"]
        self.assertEqual([row["status"] for row in person["requests"]], ["met", "met"])
        self.assertTrue(all(m["status"] == "posting" for m in person["months"]))
        self.assertEqual(Counter(m["label"] for m in person["months"])["IMH Forensic Psychiatry"], 3)
        self.assertEqual([(row["label"], row["assigned"]) for row in draft["capacity_overflows"]], [(label, 1)] * 6)

    def test_blank_elective_duration_fits_alongside_dated_mixed_posting(self):
        book = r5_book()
        imported = parse_workbook(structured_workbook_bytes())
        book["postings"]["electives"].append(next(
            row for row in imported["postings"]["electives"] if row.get("additional_requirement")))
        source = book["residents"][0]["source"]
        book["requests"] = [
            {"posting_request": label, "period": period, "matched_resident_source": source}
            for label, period in (("IMH Geriatric Psychiatry", "Jul - Sep 2027"),
                                  ("IMH Forensic Psychiatry (Elective)", None),
                                  ("IMH Child and EPIP", "Jan - Jun 2028"))]
        draft = draft_schedule(book, STORE)
        self.assertIn(draft["status"], {"optimal", "feasible"}, draft["blockers"])
        person, = draft["residents"]
        self.assertEqual([row["status"] for row in person["requests"]], ["met"] * 3)
        self.assertEqual([m["label"] for m in person["months"]],
                         ["IMH Geriatric Psychiatry"] * 3 + ["IMH Forensic Psychiatry"] * 3
                         + ["IMH Child and EPIP"] * 6)
        self.assertFalse(person["carryforward"])

    def test_requested_extended_r5_cores_are_six_continuous_months(self):
        for child, geri, elective in ((3, 3, 6), (6, 3, 3), (3, 6, 3), (6, 6, 0)):
            with self.subTest(child=child, geri=geri):
                book = r5_book()
                source = book["residents"][0]["source"]
                periods = []
                if child == 6:
                    periods.append(("IMH Child & Adolescent Psychiatry", "Jul - Dec 2027"))
                if geri == 6:
                    periods.append(("IMH Geriatric Psychiatry", "Jan - Jun 2028"))
                book["requests"] = [{"posting_request": label, "period": period, "matched_resident_source": source}
                                    for label, period in periods]
                draft = draft_schedule(book, STORE)
                self.assertIn(draft["status"], {"optimal", "feasible"}, draft["blockers"])
                person, = draft["residents"]
                self.assertTrue(all(row["status"] == "met" for row in person["requests"]))
                self.assertEqual(Counter(m["target"]["requirement_id"] for m in person["months"]),
                                 Counter({"r5.child_adolescent_psychiatry": child, "r5.geriatric_psychiatry": geri, "r5.elective": elective}))
                self.assertFalse(person["carryforward"])
                for row in person["requests"]:
                    self.assertEqual(len(row["matched_months"]), 6)
                    labels = {m["label"] for m in person["months"] if m["month"] in row["matched_months"]}
                    self.assertEqual(len(labels), 1)

    def test_additional_credit_does_not_drop_partly_completed_core_or_interrupted_historical_posting(self):
        book = r5_book()
        imported = parse_workbook(structured_workbook_bytes())
        credit = next(row for row in imported["postings"]["electives"] if row.get("additional_requirement"))
        book["postings"]["electives"].append(credit)
        for sheet in book["annual_sheets"]:
            for past in sheet["residents"]:
                if past is not book["residents"][0]:
                    for month in past["postings"]:
                        month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
        partial = resident([("2027-06", "IMH Child & Adolescent Psychiatry")], "R5", "R5 history")
        book["annual_sheets"].append({"residents": [partial]})
        draft = draft_schedule(book, STORE)
        self.assertIn(draft["status"], {"optimal", "feasible"}, draft["blockers"])
        person, = draft["residents"]
        self.assertEqual([m["label"] for m in person["months"][:2]],
                         ["IMH Child & Adolescent Psychiatry"] * 2)
        self.assertTrue(all(m["status"] == "posting" for m in person["months"][:11]))
        self.assertEqual(person["months"][-1]["status"], "requirements_completed")

        partial["postings"][0]["value"] = "IMH Child and EPIP (Elective)"
        draft = draft_schedule(book, STORE)
        self.assertIn(draft["status"], {"optimal", "feasible"}, draft["blockers"])
        person, = draft["residents"]
        self.assertEqual([m["label"] for m in person["months"][:5]], ["IMH Child and EPIP"] * 5)
        # The six-month run can continue into July and count the historical June.
        self.assertEqual(person["months"][-1]["status"], "requirements_completed")

    def test_historical_extended_core_keeps_credit_and_continues_remaining_months(self):
        for credited in (4, 6):
            with self.subTest(credited=credited):
                book = r5_book()
                for sheet in book["annual_sheets"]:
                    for person in sheet["residents"]:
                        if person is not book["residents"][0]:
                            for month in person["postings"]:
                                month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
                role = "Child & Adolescent Psychiatry"
                # Historical completed blocks may have been at different sites.
                history = [(f"2027-{month:02d}", f"{'KKH' if credited == 6 and month < 4 else 'IMH'} {role}")
                           for month in range(7 - credited, 7)]
                book["annual_sheets"].append({"residents": [resident(history, "R5", "Core history")]})
                result = draft_schedule(book, STORE)
                self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
                person, = result["residents"]
                self.assertEqual([m["label"] for m in person["months"][:6-credited]], [f"IMH {role}"] * (6 - credited))
                self.assertEqual(sum(m["status"] == "posting" for m in person["months"]), 12 - credited)
                self.assertEqual(person["months"][-1]["status"], "requirements_completed")

    def test_absent_core_catalogue_is_reported_not_synthesised(self):
        book = r5_book()
        book["postings"]["core"] = [o for o in book["postings"]["core"] if o["residency_year"] != "R5"]
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("missing_r5_catalogue_option", [r["code"] for r in result["skipped_residents"][0]["reasons"]])


class R5ElectiveBlockTests(unittest.TestCase):
    def option(self, posting, institution="IMH", remarks=()):
        return {"requirement_id": "r5.elective", "category": "elective", "posting": posting,
                "institution": institution, "label": institution + " " + posting, "remarks": list(remarks)}

    def routes(self, history, options=None, allow_split=False):
        from rules.r5_rules import prepare_routes, R5_CORES
        credited = sum(m["status"] == "expected" for m in history)
        cores = [{"requirement_id": key, "required_months": 3, "remaining_months": 0} for key in R5_CORES]
        for i, key in enumerate(R5_CORES):
            history = [{"month": f"2026-{(i * 3) + m:02d}", "requirement_id": key, "posting": key,
                        "institution": "IMH", "status": "expected"} for m in (1, 2, 3)] + history
        person = {"source": {"sheet": "Planning", "row": 3}, "months": sorted(history, key=lambda m: m["month"]),
                  "requirements": cores + [{"requirement_id": "r5.elective", "required_months": 6,
                                    "expected_months": credited, "remaining_months": max(0, 6 - credited)}]}
        errors = []
        routes = prepare_routes(person, options or [self.option("A"), self.option("B", "TTSH")],
                                errors, allow_split)
        return routes, errors

    def history(self, start, count, posting="A", institution="IMH"):
        return [{"month": f"2027-{month:02d}", "status": "expected", "requirement_id": "r5.elective",
                 "posting": posting, "institution": institution} for month in range(start, start + count)]

    def test_fresh_choices_and_mandatory_workbook_durations(self):
        from rules.r5_rules import elective_durations, supported_option
        routes, errors = self.routes([])
        self.assertFalse(errors)
        self.assertEqual([[r["remaining_months"] for r, _, _ in route] for route in routes], [[6]])
        routes, errors = self.routes([], allow_split=True)
        self.assertFalse(errors)
        self.assertEqual([[r["remaining_months"] for r, _, _ in route] for route in routes], [[6], [3, 3]])
        self.assertEqual(len({r["block_id"] for r, _, _ in routes[1]}), 2)
        six = self.option("A", remarks=[{"text": "(all required 6 months duration)"}])
        three = self.option("B", "TTSH", [{"text": "(3 months- that can be paired with any other institution)"}])
        label_six = self.option("C (6 months)", "TTSH")
        self.assertEqual(elective_durations(six), (6,))
        self.assertEqual(elective_durations(three), (3,))
        self.assertEqual(elective_durations(label_six), (6,))
        self.assertFalse(supported_option(self.option("D", remarks=[{"text": "(which will meet the core 3months R5 requirements)"}])))
        routes, errors = self.routes([], [six, three, label_six], allow_split=True)
        self.assertFalse(errors)
        self.assertEqual([[o["posting"] for o in eligible] for _, eligible, _ in routes[0]], [["A", "C (6 months)"]])
        self.assertTrue(all([o["posting"] for o in eligible] == ["B"] for _, eligible, _ in routes[1]))

    def test_completed_three_can_change_site_but_partial_blocks_must_resume(self):
        three = self.option("A", remarks=[{"text": "(3 months- that can be paired with any other institution)"}])
        options = [three, self.option("B", "TTSH")]
        for count in (1, 3, 4):
            with self.subTest(count=count):
                history = self.history(7 - count, count)
                routes, errors = self.routes(history, options if count == 1 else None)
                self.assertFalse(errors)
                if count == 1:
                    self.assertEqual([[r["remaining_months"] for r, _, _ in route] for route in routes], [[2, 3]])
                    first, eligible, partial = routes[0][0]
                    self.assertTrue(partial)
                    self.assertEqual(first["required_months"], 3)
                    self.assertEqual([(o["posting"], o["institution"]) for o in eligible], [("A", "IMH")])
                elif count == 3:
                    self.assertTrue(any(not partial and any(o["institution"] == "TTSH" for o in eligible)
                                        for route in routes for _, eligible, partial in route))
                else:
                    self.assertEqual([[r["remaining_months"] for r, _, _ in route] for route in routes], [[2]])
                    self.assertEqual(routes[0][0][0]["required_months"], 6)
                    self.assertTrue(routes[0][0][2])
        for count in (4, 5):
            routes, errors = self.routes(self.history(7 - count, count), options)
            self.assertFalse(errors)
            block, eligible, partial = routes[0][0]
            self.assertEqual((block["required_months"], block["remaining_months"], partial), (3, 6 - count, True))
            self.assertEqual([o["institution"] for o in eligible], ["IMH"])
        history = self.history(1, 3) + [{"month": "2027-04", "status": "blank"}]
        routes, errors = self.routes(history)
        self.assertFalse(errors)
        self.assertTrue(any(not route[0][2] for route in routes))
        routes, errors = self.routes(self.history(4, 1))
        self.assertFalse(errors)
        self.assertTrue(all(route[0][2] and route[0][1][0]["institution"] == "IMH" for route in routes))
        for offering, duration in ((self.option("A"), 6), (three, 3)):
            routes, errors = self.routes(self.history(1, 2) + self.history(5, 2), [offering], allow_split=True)
            self.assertFalse(errors)
            self.assertEqual([(r["required_months"], r["remaining_months"]) for r, _, _ in routes[0]], [(duration, 2)])
            self.assertEqual(len(routes), 1)
        another_three = self.option("B", "TTSH", three["remarks"])
        routes, errors = self.routes(self.history(2, 1) + self.history(6, 1, "B", "TTSH"),
                                    [three, another_three])
        self.assertFalse(errors)
        self.assertEqual([(r["remaining_months"], eligible[0]["label"], partial)
                          for r, eligible, partial in routes[0]], [(2, "IMH A", True), (2, "TTSH B", True)])
        # LOA pauses the final partial block and keeps its site binding.
        history = self.history(2, 3) + self.history(5, 1, "B", "TTSH") + [{"month": "2027-06", "status": "loa"}]
        routes, errors = self.routes(history)
        self.assertFalse(errors)
        self.assertEqual(routes[0][0][0]["remaining_months"], 2)
        self.assertEqual(routes[0][0][0]["required_months"], 3)
        self.assertEqual(routes[0][0][1][0]["institution"], "TTSH")
        # Already counted six-month totals are preserved, including old 4+2 history.
        routes, errors = self.routes(self.history(1, 4) + self.history(5, 2, "B", "TTSH"))
        self.assertEqual(routes, [[]])
        self.assertFalse(errors)


    def test_partial_block_remainder_pauses_for_loa_and_carries_the_next_block(self):
        from ortools.sat.python import cp_model
        from rules.r5_rules import add_routes
        for duration, credited in ((3, 1), (6, 4)):
            with self.subTest(duration=duration):
                note = "(3 months- that can be paired with any other institution)" if duration == 3 else "(all required 6 months duration)"
                options = [self.option("A", remarks=[{"text": note}]), self.option("B", "TTSH")]
                routes, errors = self.routes(self.history(7 - credited, credited), options)
                self.assertFalse(errors)
                person = {"availability": [{"available": False}, {"available": True}, {"available": True}]}
                model = cp_model.CpModel()
                placements = add_routes(model, person, routes, 0, 0)
                if duration == 3:
                    # The next completed block is allowed at a different service/site.
                    for p in placements:
                        if p["block_id"] == "r5.block.3" and p["option"]["institution"] != "TTSH":
                            model.add(p["variable"] == 0)
                self.assertEqual(model.validate(), "")
                solver = cp_model.CpSolver()
                self.assertEqual(solver.solve(model), cp_model.OPTIMAL)
                chosen = [p for p in placements if solver.value(p["variable"])]
                continuation = next(p for p in chosen if p["months"])
                self.assertEqual(continuation["months"], [1, 2])
                self.assertEqual(continuation["block_duration"], duration)
                self.assertEqual(continuation["option"]["label"], "IMH A")
                self.assertEqual(sum(p["remaining"] for p in chosen), 3 if duration == 3 else 0)
                if duration == 3:
                    self.assertEqual(next(p["option"]["label"] for p in chosen if p["remaining"]), "TTSH B")


if __name__ == "__main__":
    unittest.main()
