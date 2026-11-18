"""R1 draft checks validate constraints rather than a particular timetable."""
import unittest
from collections import Counter
from copy import deepcopy
from unittest.mock import patch

from ortools.sat.python import cp_model

from history_review import ReviewStore
from programme_requirements import PROGRAMME_REQUIREMENTS
from tests.catalogue_fixtures import INSTITUTIONS
from scheduler import draft_schedule, _allocation_targets, _solve_priorities, _capacity_overflow_lower_bound
from rules.r1_rules import add_preferences, prepare_candidates
from scheduler_inputs import prepare_scheduler_inputs
from cluster_coverage import CLUSTERS
from tests.test_requirement_ledger import resident
from tests import test_workbook_import


STORE = ReviewStore(version=1, decisions=[])


def r1_book(size=1):
    workbook = test_workbook_import.IncomingIntakeTests().parse([("New Resident", "NEW", "R1", 2027)]
        + [(f"Resident {n}", None, "R1", 2027) for n in range(2, size + 1)])
    workbook["residents"] = workbook["residents"][:size]
    for person in workbook["residents"]:
        for month in person["postings"]:
            month.update(status="blank", value=None)
    workbook["issues"], workbook["requests"] = [], []
    workbook["annual_sheets"] = [{"residents": workbook["residents"]}]
    workbook["histories"] = []
    core = []
    for posting, rule in PROGRAMME_REQUIREMENTS["R1"].items():
        for institution in INSTITUTIONS["R1"][posting]:
            core.append({"residency_year": "R1", "posting": f"{institution} {posting}",
                         "duration_months": str(rule["months"]), "max": None,
                         "remarks": "To be completed in the " + ("second" if posting == "Inpatient Psychiatry" else "first") + " 6 months of R1",
                         "source": {"sheet": "Postings", "row": len(core) + 2}})
    workbook["postings"] = {"core": core, "electives": []}
    return workbook


def set_history(workbook, values):
    person = workbook["residents"][0]
    person.update(name="Alex Example", mcr="M001", intake="2026", residency_year="R1")
    history = resident([(f"{2026 + (i + 6) // 12}-{(i + 6) % 12 + 1:02d}", value) for i, value in enumerate(values)], "R1")
    workbook["annual_sheets"].insert(0, {"residents": [history]})
    return history



def leave_after(workbook, active_months):
    for month in workbook["residents"][0]["postings"][active_months:]:
        month.update(status="loa", value="LOA")


class R1SolverTests(unittest.TestCase):
    def test_fresh_resident_can_split_medicine_around_neurology_at_both_pairings(self):
        prepared = prepare_scheduler_inputs(r1_book(), STORE)
        blockers = []
        _, candidates, _ = prepare_candidates(prepared["residents"], prepared["catalogue_options"],
                                              prepared["planning_start"], blockers)
        self.assertEqual(blockers, [])
        sequences = {(choice["route"], tuple(option["label"] for option in choice["schedule"][:6]))
                     for choice in candidates[0]}
        for route, medicine, neurology in (("TTSH/NNI", "TTSH", "NNI"), ("SGH", "SGH", "SGH")):
            with self.subTest(route=route):
                expected = ((f"{medicine} General Medicine",) * 2 + (f"{neurology} Neurology",) * 2
                            + (f"{medicine} General Medicine",) * 2)
                self.assertIn((route, expected), sequences)

    def test_structured_medicine_lengths_constrain_new_blocks_and_allow_carryforward(self):
        workbook = r1_book()
        for row in workbook["postings"]["core"]:
            if row["posting"].endswith("General Medicine"):
                row.update(allowed_block_lengths=[2, 4], fulfils_requirements=["General Medicine"],
                           additional_requirement=None, additional_credit_months=None)
        prepared = prepare_scheduler_inputs(workbook, STORE)
        person = prepared["residents"][0]

        def paired_sequences():
            blockers = []
            _, candidates, _ = prepare_candidates([person], prepared["catalogue_options"],
                                                  prepared["planning_start"], blockers)
            self.assertFalse(blockers)
            return [
                (tuple(o["requirement_id"].removeprefix("r1.") for o in c["schedule"] if o), c["carryforward"])
                for c in candidates[0] if c["route"] == "TTSH/NNI"
            ]

        gm, neuro = "general_medicine", "neurology"
        self.assertEqual({sequence[:6] for sequence, _ in paired_sequences()},
                         {(gm,) * 4 + (neuro,) * 2, (neuro,) * 2 + (gm,) * 4,
                          (gm,) * 2 + (neuro,) * 2 + (gm,) * 2})

        for month in person["availability"][:-1]:
            month["available"] = False
        self.assertTrue(any(sequence == (gm,) and carry[("r1.general_medicine", "TTSH")] == 3
                            for sequence, carry in paired_sequences()))

    def check_resident(self, person):
        active = [m for m in person["months"] if m["status"] == "posting"]
        counts = Counter(m["target"]["requirement_id"] for m in active)
        self.assertEqual(len(active), 12)
        self.assertTrue(all(m["target"]["requirement_id"] != "r1.inpatient_psychiatry" for m in active[:6]))
        self.assertTrue(all(m["target"]["requirement_id"] == "r1.inpatient_psychiatry" for m in active[6:]))
        self.assertEqual(len({m["label"] for m in active[6:]}), 1)
        if person["route"] == "NUH":
            self.assertEqual(counts["r1.medicine_neurology"], 6)
            self.assertTrue(all(m["target"]["institution"] == "NUH" for m in active[:6]))
        else:
            self.assertEqual((counts["r1.general_medicine"], counts["r1.neurology"]), (4, 2))
            neuro = [i for i, m in enumerate(active) if m["target"]["requirement_id"] == "r1.neurology"]
            self.assertEqual(neuro[1] - neuro[0], 1)
            pair = {m["target"]["institution"] for m in active[:6]}
            self.assertEqual(pair, {"TTSH", "NNI"} if person["route"] == "TTSH/NNI" else {"SGH"})
        self.assertEqual(person["carryforward"], [])

    def test_full_routes_have_exact_duration_training_windows_pairing_and_labels(self):
        workbook = r1_book(24)
        original = deepcopy(workbook)
        result = draft_schedule(workbook, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"})
        self.assertEqual({p["route"] for p in result["residents"]}, {"TTSH/NNI", "SGH", "NUH"})
        labels = {r["posting"] for r in workbook["postings"]["core"]}
        for person in result["residents"]:
            self.check_resident(person)
            self.assertTrue(all(m["label"] in labels for m in person["months"]))
        self.assertEqual(result["soft_results"]["ratio_deviation"], 0)
        self.assertEqual(result["soft_results"]["inpatient_counts"], {"IMH": 8, "TTSH": 4, "CGH": 4, "SGH": 4, "NUH": 4})
        self.assertEqual(result["singletons"], [])
        for person in result["residents"]:
            preferred = {"TTSH/NNI": ("SHS", "NUHS"), "SGH": ("NHG", "NUHS"), "NUH": ("NHG", "SHS")}[person["route"]]
            self.assertTrue(any(person["months"][-1]["target"]["institution"] in CLUSTERS[cluster]
                                for cluster in preferred))
        self.assertEqual(workbook, original)

    def test_inpatient_candidates_follow_catalogue_instead_of_fixed_sites(self):
        workbook = r1_book()
        core = workbook["postings"]["core"]
        inpatient = next(row for row in core if row["posting"] == "IMH Inpatient Psychiatry")
        workbook["postings"]["core"] = [row for row in core if "Inpatient Psychiatry" not in row["posting"]]
        workbook["postings"]["core"].append({**inpatient, "posting": "AH Inpatient Psychiatry"})
        result = draft_schedule(workbook, STORE)
        self.assertIn(result["status"], {"optimal", "feasible"}, result["blockers"])
        self.check_resident(result["residents"][0])
        self.assertEqual([m["label"] for m in result["residents"][0]["months"][6:]],
                         ["AH Inpatient Psychiatry"] * 6)

    def test_continuing_history_preserves_pairing_neuro_block_and_only_schedules_remaining(self):
        workbook = r1_book()
        set_history(workbook, ["TTSH General Medicine"] * 2 + ["NNI Neurology"] * 2 + ["TTSH General Medicine"] * 2
                    + ["LOA"] * 3 + ["IMH Inpatient Psychiatry"] * 3)
        from tests.test_r2_rules import r2_book
        r2 = r2_book()["postings"]
        workbook["postings"]["core"].extend(o for o in r2["core"] if o["residency_year"] == "R2")
        workbook["postings"]["electives"] = r2["electives"]
        result = draft_schedule(workbook, STORE)
        self.assertEqual(result["status"], "optimal")
        person = result["residents"][0]
        self.assertEqual(person["route"], "TTSH/NNI")
        self.assertEqual(person["credited_r1_months"], 9)
        self.assertEqual([m["label"] for m in person["months"][:3]], ["IMH Inpatient Psychiatry"] * 3)
        self.assertTrue(all(m["target"]["residency_year"] == "R2" for m in person["months"][3:]))
        self.assertEqual(sum(item["months"] for item in person["carryforward"]), 3)
        self.assertEqual(result["soft_targets"]["active_incoming_cohort_size"], 0)
        # Past timing exceptions and blank/missing calendar months do not undo credit.
        for gap in (False, True):
            with self.subTest(historical_gap=gap):
                exceptional = r1_book()
                medicine = next(row for row in exceptional["postings"]["core"] if row["posting"] == "SGH General Medicine")
                medicine.update(allowed_block_lengths=[2, 4], fulfils_requirements=["General Medicine"],
                                additional_requirement=None, additional_credit_months=None)
                values = ["SGH General Medicine"] + ["LOA"] * 5 + ["IMH Inpatient Psychiatry"] * 6
                if gap:
                    values[1] = None
                history = set_history(exceptional, values)
                if gap:
                    history["postings"].pop(2)
                    exceptional["residents"][0]["intake"] = None
                leave_after(exceptional, 5)
                original = deepcopy(exceptional)
                draft = draft_schedule(exceptional, STORE)
                self.assertEqual(draft["status"], "optimal")
                person = draft["residents"][0]
                self.assertEqual(person["route"], "SGH")
                self.assertEqual(person["credited_r1_months"], 7)
                self.assertEqual(Counter(m["label"] for m in person["months"] if m["status"] == "posting"),
                                 {"SGH General Medicine": 3, "SGH Neurology": 2})
                self.assertEqual(sum(m["status"] == "loa" for m in person["months"]), 7)
                self.assertEqual(exceptional, original)
        # Cross-pair history still counts; future assignments form one valid pair.
        exceptional = r1_book()
        set_history(exceptional, ["TTSH General Medicine", "SGH Neurology"] + ["IMH Inpatient Psychiatry"] * 6 + [None] * 4)
        leave_after(exceptional, 4)
        person = draft_schedule(exceptional, STORE)["residents"][0]
        future = [m for m in person["months"] if m["status"] == "posting"]
        self.assertEqual(Counter(m["target"]["requirement_id"] for m in future),
                         {"r1.general_medicine": 3, "r1.neurology": 1})
        self.assertIn({m["target"]["institution"] for m in future}, ({"TTSH", "NNI"}, {"SGH"}))
        # Excess credited months and split inpatient sites never create negative remainders.
        exceptional = r1_book()
        set_history(exceptional, ["TTSH General Medicine"] * 5 + ["SGH Neurology"] * 3
                    + ["IMH Inpatient Psychiatry"] * 2 + ["SGH Inpatient Psychiatry"] * 2)
        leave_after(exceptional, 2)
        person = draft_schedule(exceptional, STORE)["residents"][0]
        self.assertEqual(person["credited_r1_months"], 10)
        self.assertEqual(Counter(m["target"]["requirement_id"] for m in person["months"] if m["status"] == "posting"),
                         {"r1.inpatient_psychiatry": 2})
        self.assertEqual(person["carryforward"], [])
        # A completed combined route beats unused alternative requirements.
        exceptional = r1_book()
        set_history(exceptional, ["NUH Medicine & Neurology"] * 6 + ["TTSH General Medicine"] + [None] * 5)
        leave_after(exceptional, 6)
        person = draft_schedule(exceptional, STORE)["residents"][0]
        self.assertEqual(person["route"], "NUH")
        self.assertEqual(Counter(m["target"]["requirement_id"] for m in person["months"] if m["status"] == "posting"),
                         {"r1.inpatient_psychiatry": 6})

    def test_loa_pauses_training_and_unfinished_requirements_carry_past_june(self):
        workbook = r1_book()
        for month in workbook["residents"][0]["postings"][:3]:
            month.update(status="loa", value="LOA")
        original = deepcopy(workbook)
        result = draft_schedule(workbook, STORE)
        self.assertEqual(result["status"], "optimal")
        person = result["residents"][0]
        self.assertTrue(all(m["status"] == "loa" and m["label"] is None for m in person["months"][:3]))
        active = [m for m in person["months"] if m["status"] == "posting"]
        self.assertEqual(len(active), 9)
        self.assertTrue(all(m["target"]["requirement_id"] != "r1.inpatient_psychiatry" for m in active[:6]))
        self.assertTrue(all(m["target"]["requirement_id"] == "r1.inpatient_psychiatry" for m in active[6:]))
        self.assertEqual(person["carryforward"], [{"requirement_id": "r1.inpatient_psychiatry", "institution": active[-1]["target"]["institution"], "months": 3}])
        self.assertEqual(workbook, original)
        for month in workbook["residents"][0]["postings"]:
            month.update(status="loa", value="LOA")
        paused = draft_schedule(workbook, STORE)
        self.assertEqual(paused["status"], "optimal")
        self.assertEqual(paused["soft_targets"]["active_incoming_cohort_size"], 0)
        self.assertEqual(sum(item["months"] for item in paused["residents"][0]["carryforward"]), 12)
        self.assertTrue(all(m["status"] == "loa" for m in paused["residents"][0]["months"]))

    def test_capacity_lower_bound_never_exceeds_enumerated_overflow(self):
        from itertools import product
        # Choice lengths include LOA/partial carryforward and future-only zero.
        for capacity, tail in product((0, 1, None), ([], [1], [0, 1])):
            option = {"requirement_id": "r4.emergency", "institution": "IMH", "label": "IMH Emergency", "capacity": capacity}
            r1_option = dict(option, requirement_id="r1.neurology", label="IMH Neurology")
            candidates = [[{"schedule": [r1_option, None]}, {"schedule": [None, r1_option]}]]
            placements = [[{"option": option, "block_id": "partial", "months": [0]},
                           {"option": option, "block_id": "partial", "months": [1]},
                           {"option": option, "block_id": "tail", "months": tail}]]
            blocks = [[({"requirement_id": option["requirement_id"], "block_id": identity}, [], False)
                       for identity in ("partial", "tail")]]
            fixed = {(0, option["requirement_id"], "IMH", option["label"]): [{"name": "Known occupant"}]}
            bound = _capacity_overflow_lower_bound(candidates, placements, blocks, [option, r1_option], fixed, 2)
            scores = []
            for path, partial in product(candidates[0], placements[0][:2]):
                counts = Counter({(0, option["requirement_id"]): 1})
                counts.update((m, o["requirement_id"]) for m, o in enumerate(path["schedule"]) if o)
                counts.update((m, option["requirement_id"]) for m in partial["months"] + tail)
                scores.append(sum(max(0, count - capacity) for count in counts.values()) if capacity is not None else 0)
            self.assertLessEqual(bound, min(scores))
            if capacity == 0:
                self.assertEqual(bound, 3 + len(tail))
            if capacity is None:
                self.assertEqual(bound, 0)
        capped = {"requirement_id": "r1.neurology", "capacity": 0}
        unlimited_alternative = dict(capped, institution="Other", capacity=None)
        split = {"schedule": [capped, capped]}
        combined_option = {"requirement_id": "r1.combined", "capacity": 0}
        combined = {"schedule": [combined_option, combined_option]}
        self.assertEqual(_capacity_overflow_lower_bound([[split]], [[]], [[]],
                         [capped, unlimited_alternative], {}, 2), 0)
        # Neither split nor combined demand is mandatory across alternative routes.
        bound = _capacity_overflow_lower_bound([[split, combined]], [[]], [[]], [capped, combined_option], {}, 2)
        self.assertEqual(bound, 0)
        self.assertLessEqual(bound, 2)  # Enumerated optimum: either route consumes two zero-Max months.


    def test_capacity_blank_zero_and_monthly_overflow_are_soft_targets(self):
        workbook = r1_book(3)
        self.assertEqual(draft_schedule(workbook, STORE)["status"], "optimal")
        for row in workbook["postings"]["core"]:
            row["max"] = "2" if row["posting"] == "TTSH General Medicine" else "1" if row["posting"] == "NNI Neurology" else "0" if "Inpatient" not in row["posting"] else None
        result = draft_schedule(workbook, STORE)
        self.assertEqual(result["status"], "optimal")
        self.assertEqual(len(result["singletons"]), 6)
        self.assertTrue(all(item["label"] == "NNI Neurology" for item in result["singletons"]))
        for month in range(6):
            counts = Counter(p["months"][month]["label"] for p in result["residents"])
            self.assertEqual(counts, {"TTSH General Medicine": 2, "NNI Neurology": 1})
        for row in workbook["postings"]["core"]:
            if "Inpatient" not in row["posting"]:
                row["max"] = "0"
        impossible = draft_schedule(workbook, STORE)
        self.assertEqual(impossible["status"], "optimal")
        self.assertEqual(impossible["soft_results"]["capacity_overflow"], 18)
        self.assertEqual(sum(row["assigned"] - row["max"] for row in impossible["capacity_overflows"]), 18)
        self.assertTrue(all(row["assigned"] == len(row["residents"]) for row in impossible["capacity_overflows"]))
        shared = r1_book()
        next(row for row in shared["postings"]["core"] if row["posting"] == "IMH Inpatient Psychiatry")["max"] = "1"
        outside = resident([(m["month"], "IMH Inpatient Psychiatry") for m in shared["months"]], "R5", "Planning", 100)
        shared["residents"].append(outside)
        blocked = draft_schedule(shared, STORE)
        self.assertIn(blocked["status"], {"optimal", "feasible"})
        self.assertEqual(len(blocked["skipped_residents"]), 1)
        self.assertEqual(blocked["blockers"], [])
        self.assertEqual(blocked["capacity_coverage_notes"], [])
        next(row for row in shared["postings"]["core"] if row["posting"] == "IMH Inpatient Psychiatry")["max"] = "0"
        occupied = draft_schedule(shared, STORE)
        self.assertEqual(occupied["soft_results"]["capacity_overflow"], 12)
        self.assertEqual(len(occupied["capacity_overflows"]), 12)
        self.assertTrue(all(row["assigned"] == 1 and row["residents"][0]["source"] == outside["source"]
                            for row in occupied["capacity_overflows"]))

    def test_completed_resident_retained_cells_still_consume_known_capacity(self):
        from tests.test_r5_rules import r5_book
        book = r5_book()
        for sheet in book["annual_sheets"]:
            for past in sheet["residents"]:
                if past is not book["residents"][0]:
                    for month in past["postings"]:
                        month["month"] = str(int(month["month"][:4]) - 1) + month["month"][4:]
        labels = (["IMH Geriatric Psychiatry"] * 3 + ["IMH Child & Adolescent Psychiatry"] * 3
                  + ["IMH Forensic Psychiatry (Elective)"] * 6)
        book["annual_sheets"].append({"residents": [resident([
            (f"{2026 + (i + 6) // 12}-{(i + 6) % 12 + 1:02d}", label) for i, label in enumerate(labels)], "R5")]})
        for posting in book["residents"][0]["postings"]:
            posting.update(status="posting", value="IMH Forensic Psychiatry (Elective)")
        next(row for row in book["postings"]["electives"] if row["residency_year"] == "R5")["max"] = "0"
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "optimal")
        self.assertTrue(all(month["status"] == "outside_draft_scope" for month in result["residents"][0]["months"]))
        self.assertEqual(result["soft_results"]["capacity_overflow"], 12)
        self.assertEqual(len(result["capacity_overflows"]), 12)
        self.assertEqual(result["capacity_coverage_notes"], [])
        self.assertTrue(all(row["residents"][0]["source"] == book["residents"][0]["source"] for row in result["capacity_overflows"]))

    def test_incoming_targets_24_23_are_soft_and_relax_under_capacity(self):
        for size, targets in ((24, {"TTSH/NNI": 12, "SGH": 9, "NUH": 3}), (23, {"TTSH/NNI": 12, "SGH": 9, "NUH": 2})):
            with self.subTest(size=size):
                result = draft_schedule(r1_book(size), STORE)
                self.assertIn(result["status"], {"optimal", "feasible"})
                self.assertEqual(result["soft_targets"]["routes"], targets)
                self.assertEqual(result["soft_results"]["route_counts"], targets)
                self.assertEqual(result["soft_results"]["distribution_deviation"], 0)
        workbook = r1_book(23)
        next(row for row in workbook["postings"]["core"] if row["posting"] == "NUH Medicine & Neurology")["max"] = "0"
        relaxed = draft_schedule(workbook, STORE)
        self.assertIn(relaxed["status"], {"optimal", "feasible"})
        self.assertEqual(relaxed["soft_results"]["route_counts"]["NUH"], 0)
        self.assertGreater(relaxed["soft_results"]["distribution_deviation"], 0)

    def test_weighted_inpatient_targets_and_small_cohorts(self):
        sites = ["IMH", "TTSH", "CGH", "SGH", "NUH"]
        for size, imh, other in ((0, 0, 0), (2, 2, 0), (18, 6, 3), (20, 8, 3),
                                 (21, 9, 3), (22, 10, 3), (23, 11, 3), (24, 8, 4)):
            with self.subTest(size=size):
                self.assertEqual(_allocation_targets(size, sites),
                                 {site: imh if site == "IMH" else other for site in sites})
        self.assertEqual(_allocation_targets(6, ["IMH", "NUH"]), {"IMH": 4, "NUH": 2})
        self.assertEqual(_allocation_targets(6, ["NUH"]), {})

    def test_destination_preference_uses_cluster_membership_for_catalogue_sites(self):
        # These sites were absent from the old destination list. An unknown
        # cluster must not accidentally receive a preference bonus.
        for route, penalties in (("TTSH/NNI", {"AH": 0, "SKH": 0, "KTPH": 1, "UNKNOWN": 1}),
                                 ("SGH", {"AH": 0, "SKH": 1, "KTPH": 0, "UNKNOWN": 1}),
                                 ("NUH", {"AH": 1, "SKH": 0, "KTPH": 0, "UNKNOWN": 1})):
            for site, expected in penalties.items():
                with self.subTest(route=route, site=site):
                    model = cp_model.CpModel()
                    choice = model.new_bool_var("choice")
                    model.add(choice == 1)
                    candidates = [[{"route": route, "schedule": [{"institution": site,
                        "requirement_id": "r1.inpatient_psychiatry"}]}]]
                    preferences = add_preferences(model, candidates, [[choice]], [False], [])
                    solver = cp_model.CpSolver()
                    self.assertEqual(solver.solve(model), cp_model.OPTIMAL)
                    self.assertEqual(solver.value(preferences["destination"]), expected)

    def test_allocation_overrides_destination_but_capacity_overrides_allocation(self):
        book = r1_book()
        draft = draft_schedule(book, STORE)
        self.assertEqual(draft["residents"][0]["route"], "TTSH/NNI")
        self.assertEqual(draft["soft_results"]["inpatient_counts"]["IMH"], 1)
        self.assertEqual(draft["soft_results"]["destination_deviation"], 1)
        book = r1_book(6)
        next(row for row in book["postings"]["core"] if row["posting"] == "IMH Inpatient Psychiatry")["max"] = "1"
        draft = draft_schedule(book, STORE)
        self.assertEqual(draft["status"], "optimal")
        self.assertLessEqual(draft["soft_results"]["inpatient_counts"]["IMH"], 1)
        self.assertGreater(draft["soft_results"]["inpatient_deviation"], 0)

    def test_inpatient_balances_remaining_sites_when_imh_is_unavailable(self):
        book = r1_book(4)
        book["postings"]["core"] = [row for row in book["postings"]["core"] if row["posting"] != "IMH Inpatient Psychiatry"]
        result = draft_schedule(book, STORE)
        self.assertEqual(result["status"], "optimal")
        counts = result["soft_results"]["inpatient_counts"]
        self.assertEqual([counts[site] for site in ("TTSH", "CGH", "SGH", "NUH")], [1, 1, 1, 1])
        self.assertEqual(counts.get("IMH", 0), 0)

    def test_cluster_tiebreak_uses_history_and_only_actual_scheduled_months(self):
        book = r1_book()
        set_history(book, ["TTSH General Medicine"] * 4 + ["NNI Neurology"] * 2 + [None] * 6)
        next(row for row in book["postings"]["core"] if row["posting"] == "IMH Inpatient Psychiatry")["max"] = "0"
        leave_after(book, 6)
        draft = draft_schedule(book, STORE)
        person = draft["residents"][0]
        self.assertEqual(person["months"][0]["label"], "NUH Inpatient Psychiatry")
        self.assertEqual(draft["soft_results"]["missing_clusters"], 0)
        for month in book["residents"][0]["postings"]:
            month.update(status="loa", value="LOA")
        paused = draft_schedule(book, STORE)
        self.assertEqual(paused["soft_targets"]["inpatient_residents"], 0)
        self.assertEqual(paused["soft_results"]["missing_clusters"], 1)

    def test_priority_scores_are_locked_instead_of_summed(self):
        model = cp_model.CpModel()
        choice = model.new_bool_var("choice")
        solver, status, stages, _ = _solve_priorities(
            model, [("first", choice), ("second", 100 * (1 - choice))], [choice], 2)
        self.assertEqual(status, "optimal")
        self.assertEqual(solver.value(choice), 0)
        self.assertEqual([s["score"] for s in stages], [0, 100])
        for stage in stages:
            self.assertEqual(stage["best_objective_bound"], stage["score"])
            self.assertGreaterEqual(stage["best_score_time_seconds"], 0)
            self.assertLessEqual(stage["best_score_time_seconds"], stage["wall_time_seconds"])
        constant_model = cp_model.CpModel()
        _, status, stages, _ = _solve_priorities(constant_model, [("constant", 0)], [], 2)
        self.assertEqual(status, "optimal")
        self.assertEqual(stages[0]["score"], 0)
        self.assertEqual(stages[0]["best_objective_bound"], 0)
        self.assertGreaterEqual(stages[0]["best_score_time_seconds"], 0)

    def test_timeout_retains_solution_and_feasible_does_not_advance_priority(self):
        solve = cp_model.CpSolver.solve
        for interrupted_status, expected_stages in ((cp_model.FEASIBLE, 1), (cp_model.UNKNOWN, 2)):
            model = cp_model.CpModel()
            choice = model.new_bool_var("choice")
            calls = []

            def interrupted(solver, current_model, callback=None):
                calls.append(solver.parameters.max_time_in_seconds)
                if interrupted_status == cp_model.UNKNOWN and len(calls) == 2:
                    return cp_model.UNKNOWN
                actual = solve(solver, current_model, callback)
                return cp_model.FEASIBLE if interrupted_status == cp_model.FEASIBLE else actual

            with patch("scheduler.cp_model.CpSolver.solve", new=interrupted), patch(
                    "scheduler.monotonic", side_effect=[0, 0, 0, 0.25, 0.5, 0.5, 0.75, 1]):
                solver, status, stages, _ = _solve_priorities(
                    model, [("first", choice), ("second", 1 - choice)], [choice], 2)
            self.assertEqual(status, "feasible")
            self.assertEqual(solver.value(choice), 0)
            self.assertEqual(len(stages), expected_stages)
            self.assertIn("best_objective_bound", stages[0])
            self.assertIn("best_score_time_seconds", stages[0])
            if len(calls) == 2:
                self.assertLess(calls[1], calls[0])
                self.assertNotIn("best_objective_bound", stages[1])
                self.assertNotIn("best_score_time_seconds", stages[1])
        with patch("scheduler.monotonic", side_effect=[0, 0, 0, 0.5, 3, 3]):
            solver, status, stages, _ = _solve_priorities(
                model, [("first", choice), ("second", 1 - choice)], [choice], 2)
        self.assertEqual(status, "feasible")
        self.assertEqual(len(stages), 1)

    def test_initial_draft_then_real_priority_optimisation(self):
        model = cp_model.CpModel()
        choice = model.new_bool_var("choice")
        solver, status, stages, _ = _solve_priorities(
            model, [("first", choice), ("second", 1 - choice)], [choice, choice], 2,
            initial_feasibility=True)
        self.assertEqual(status, "optimal")
        self.assertEqual(solver.value(choice), 0)
        self.assertEqual([s["priority"] for s in stages], ["initial_feasibility", "first", "second"])
        self.assertEqual(stages[0]["status"], "feasible")
        self.assertNotIn("best_objective_bound", stages[0])
        self.assertEqual(len(model.proto.solution_hint.vars), 1)

    def test_initial_fallback_shares_budget_and_survives_unknown(self):
        real_solve = cp_model.CpSolver.solve
        for budget, expected_calls in ((5, 2), (1, 1)):
            with self.subTest(budget=budget):
                model = cp_model.CpModel()
                choice = model.new_bool_var("choice")
                now, calls = [0.0], []
                add_hint = model.add_hint
                def hint(variable, value):
                    now[0] += .25
                    add_hint(variable, value)
                def build():
                    now[0] += .5
                    auxiliary = model.new_int_var(0, 1, "deferred_score")
                    model.add(auxiliary == choice)
                    return auxiliary
                def solve(solver, current, callback):
                    calls.append((solver.parameters.max_time_in_seconds,
                                  solver.parameters.stop_after_first_solution))
                    if len(calls) == 1:
                        result = real_solve(solver, current, callback)
                        now[0] += 2
                        return result
                    now[0] += solver.parameters.max_time_in_seconds
                    return cp_model.UNKNOWN
                with patch("scheduler.cp_model.CpSolver.solve", new=solve), patch(
                        "scheduler.monotonic", side_effect=lambda: now[0]), patch.object(model, "add_hint", side_effect=hint):
                    solver, status, stages, elapsed = _solve_priorities(
                        model, [("first", build)], [choice, choice], budget, initial_feasibility=True,
                        score_values=lambda solution: (solution.value(choice),))
                self.assertIsNotNone(solver)
                self.assertEqual(status, "feasible")
                self.assertEqual(len(calls), expected_calls)
                self.assertTrue(calls[0][1])
                self.assertEqual(stages[0]["status"], "feasible")
                self.assertEqual(len(model.proto.constraints), 1 if expected_calls == 2 else 0)  # Only the reached score definition; no fallback locks.
                if expected_calls == 2:
                    self.assertEqual(calls[1], (2.25, False))
                    self.assertEqual(elapsed, budget)
                    self.assertEqual(stages[1]["status"], "unknown")

    def test_unproven_normal_solution_cannot_worsen_fallback_lexicographically(self):
        real_solve = cp_model.CpSolver.solve
        for fallback, candidate, expected, normal_status in (
                ((0, 0), (0, 1), (0, 0), cp_model.FEASIBLE),
                ((1, 0), (0, 1), (0, 1), cp_model.FEASIBLE),
                ((0, 1), (0, 0), (0, 0), cp_model.FEASIBLE),
                ((0, 0), (0, 1), (0, 0), cp_model.OPTIMAL)):
            with self.subTest(fallback=fallback, candidate=candidate, normal_status=normal_status):
                model = cp_model.CpModel()
                x, y = model.new_bool_var("x"), model.new_bool_var("y")
                calls = []
                def build():
                    auxiliary = model.new_int_var(0, 1, "deferred_score")
                    model.add(auxiliary == x)
                    return auxiliary
                def solve(solver, current, callback):
                    calls.append(1)
                    if len(calls) == 3:
                        return cp_model.UNKNOWN
                    fixed = current.clone()
                    for variable, value in zip((x, y), fallback if len(calls) == 1 else candidate):
                        fixed.add(variable == value)
                    actual = real_solve(solver, fixed, callback)
                    self.assertIn(actual, (cp_model.OPTIMAL, cp_model.FEASIBLE))
                    return actual if len(calls) == 1 else normal_status
                with patch("scheduler.cp_model.CpSolver.solve", new=solve):
                    solver, status, stages, _ = _solve_priorities(
                        model, [("first", build), ("second", y)], [x, y], 2, initial_feasibility=True,
                        score_values=lambda solution: (solution.value(x), solution.value(y)))
                self.assertEqual(tuple(solver.value(v) for v in (x, y)), expected)
                self.assertEqual(status, "feasible")
                proven = normal_status == cp_model.OPTIMAL
                self.assertEqual(len(calls), 3 if proven else 2)
                self.assertEqual(len(model.proto.constraints), 2 if proven else 1)
                self.assertEqual(stages[1].get("retained_previous_solution", False), candidate > fallback)
                if candidate > fallback:
                    self.assertEqual(stages[1]["retained_score"], fallback[0])
                if proven:
                    self.assertEqual(stages[1]["score"], solver.value(x))  # Retained fallback satisfies the proof lock.
                    self.assertEqual(list(model.proto.solution_hint.values), list(expected))

    def test_bound_submodels_do_not_repeat_initial_feasibility(self):
        model, bound_model = cp_model.CpModel(), cp_model.CpModel()
        x, y = model.new_bool_var("x"), model.new_bool_var("y")
        bound = bound_model.new_bool_var("bound")
        real_solve, bound_calls = cp_model.CpSolver.solve, []
        def solve(solver, current, callback):
            if current is bound_model:
                bound_calls.append(solver.parameters.stop_after_first_solution)
            return real_solve(solver, current, callback)
        with patch("scheduler.cp_model.CpSolver.solve", new=solve), patch(
                "scheduler.r1_rules.ratio_relaxation", return_value=(bound_model, bound, [bound])), patch(
                "scheduler.R1_RATIO_BOUND_SECONDS", .1):
            _, status, stages, _ = _solve_priorities(model,
                [("incoming_route_distribution", x), ("monthly_medicine_neurology_ratio", y)],
                [x, y], 2, r1_ratio_data=(None,), initial_feasibility=True)
        self.assertEqual(status, "optimal")
        self.assertEqual(bound_calls, [False])
        self.assertEqual([s["priority"] for s in stages],
                         ["initial_feasibility", "incoming_route_distribution", "monthly_medicine_neurology_ratio"])

    def test_blocked_unknown_and_model_invalid_never_return_fake_solution(self):
        workbook = r1_book()
        unknown = draft_schedule(workbook, STORE, max_seconds=0)
        self.assertEqual(unknown["status"], "unknown")
        self.assertEqual(unknown["residents"], [])
        solve = cp_model.CpSolver.solve

        def invalid_model(solver, model, callback=None):
            model.new_int_var(1, 0, "invalid_domain")
            return solve(solver, model, callback)

        with patch("scheduler.cp_model.CpSolver.solve", new=invalid_model):
            invalid = draft_schedule(workbook, STORE)
        self.assertEqual(invalid["status"], "model_invalid")
        self.assertEqual(invalid["residents"], [])
        self.assertNotIn("best_objective_bound", invalid["optimisation_stages"][0])
        self.assertNotIn("best_score_time_seconds", invalid["optimisation_stages"][0])
        for change, expected in (("remarks", "unsupported_r1_remarks"), ("history", "unresolved_history"),
                                 ("unsafe_history", "unsafe_historical_identity_evidence_excluded"), ("identity", "unsafe_identity")):
            with self.subTest(change=change):
                changed = deepcopy(workbook)
                if change == "remarks":
                    changed["postings"]["core"][0]["remarks"] = "Compulsory unimplemented restriction"
                elif change == "history":
                    set_history(changed, ["Unknown department"] + ["LOA"] * 11)
                elif change == "unsafe_history":
                    history = set_history(changed, ["SGH General Medicine"] + [None] * 11)
                    changed["issues"] = [{"code": "duplicate_mcr", "records": [{"source": history["source"]}]}]
                else:
                    changed["issues"] = [{"code": "duplicate_mcr", "records": [{"source": changed["residents"][0]["source"]}]}]
                blocked = draft_schedule(changed, STORE)
                self.assertEqual(blocked["status"], "blocked")
                self.assertEqual(blocked["residents"], [])
                self.assertIn(expected, {b["code"] for b in blocked["blockers"]})
                self.assertTrue(all("source" in b or "sources" in b for b in blocked["blockers"]))
        unrelated = deepcopy(workbook)
        unrelated["postings"]["electives"] = [{"residency_year": "R2", "institution": "IMH", "elective": "ANDS",
            "source": {"sheet": "Postings", "row": 100}, "remarks": [{"text": "Unimplemented elective restriction", "source": {"sheet": "Postings", "row": 101}}]}]
        self.assertEqual(draft_schedule(unrelated, STORE)["status"], "optimal")


if __name__ == "__main__":
    unittest.main()
