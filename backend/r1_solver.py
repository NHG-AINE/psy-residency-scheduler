"""R1-only draft selection; no changes to uploaded postings or review decisions."""
from collections import Counter, defaultdict
from copy import deepcopy
from math import isfinite
from time import monotonic

from ortools.sat.python import cp_model

if __package__:
    from .cluster_coverage import cluster_coverage
    from .programme_requirements import PROGRAMME_REQUIREMENTS
    from .scheduler_inputs import prepare_scheduler_inputs
    from .workbook_import import match_posting, normalized_label, posting_catalogue, recorded_years
else:
    from cluster_coverage import cluster_coverage
    from programme_requirements import PROGRAMME_REQUIREMENTS
    from scheduler_inputs import prepare_scheduler_inputs
    from workbook_import import match_posting, normalized_label, posting_catalogue, recorded_years


STANDARD_ROUTE_TARGETS = {"TTSH/NNI": 12, "SGH": 9, "NUH": 3}
SHORT_COHORT_ROUTE_TARGETS = {"TTSH/NNI": 12, "SGH": 9, "NUH": 2}
STANDARD_COHORT_SIZE = sum(STANDARD_ROUTE_TARGETS.values())
SHORT_COHORT_SIZE = sum(SHORT_COHORT_ROUTE_TARGETS.values())
ROUTES = tuple(STANDARD_ROUTE_TARGETS)
PAIRED_ROUTES = ("TTSH/NNI", "SGH")
MEDICINE_PER_NEUROLOGY = 2
IMH_ALLOCATION_SHARES = 2
PREFERRED_INPATIENT_SITES = {
    "TTSH/NNI": {"SGH", "CGH", "NUH"},
    "SGH": {"IMH", "TTSH", "NUH"},
    "NUH": {"IMH", "TTSH", "SGH", "CGH"},
}
SOFT_PRIORITIES = (
    "incoming_route_distribution", "monthly_medicine_neurology_ratio",
    "singleton_months", "inpatient_allocation", "inpatient_destination", "missing_clusters",
)

DEFAULT_SOLVE_SECONDS = 10
# Keep the search reproducible for a given set of inputs.
SOLVER_WORKERS = 1
SOLVER_RANDOM_SEED = 0

R1 = PROGRAMME_REQUIREMENTS["R1"]
R1_REQUIRED_MONTHS = R1["Medicine & Neurology"]["months"] + R1["Inpatient Psychiatry"]["months"]


def _paths(person):
    """Use ledger credit, never validate the order of historical exceptions."""
    gm, neuro, combined, inpatient = [R1[name]["id"] for name in (
        "General Medicine", "Neurology", "Medicine & Neurology", "Inpatient Psychiatry")]
    remaining = {item["requirement_id"]: item["remaining_months"] for item in person["requirements"]}
    history = [month for month in person["months"] if month["status"] == "expected"]
    route_evidence = {route for month in history for route, key in (
        ("TTSH/NNI", (gm, "TTSH")), ("TTSH/NNI", (neuro, "NNI")),
        ("SGH", (gm, "SGH")), ("SGH", (neuro, "SGH")), ("NUH", (combined, "NUH")))
        if (month["requirement_id"], month["institution"]) == key}
    preferred_route = next(iter(route_evidence)) if len(route_evidence) == 1 else None
    paired_months = remaining[gm] + remaining[neuro]
    least_remaining = min(paired_months, remaining[combined])
    inpatient_sites = {month["institution"] for month in history if month["requirement_id"] == inpatient}
    sites = sorted(inpatient_sites) if len(inpatient_sites) == 1 else R1["Inpatient Psychiatry"]["institutions"]
    for site in sites:
        tail = [(inpatient, site)] * remaining[inpatient]
        if paired_months == least_remaining:
            for route, medicine_site, neuro_site in (("TTSH/NNI", "TTSH", "NNI"), ("SGH", "SGH", "SGH")):
                if preferred_route in PAIRED_ROUTES and preferred_route != route:
                    continue
                for start in range(remaining[gm] + 1):
                    head = [(gm, medicine_site)] * start + [(neuro, neuro_site)] * remaining[neuro]
                    head += [(gm, medicine_site)] * (remaining[gm] - start)
                    yield route, head + tail
        if remaining[combined] == least_remaining:
            yield "NUH", [(combined, "NUH")] * remaining[combined] + tail


def _targets(size):
    if size == SHORT_COHORT_SIZE:
        return dict(SHORT_COHORT_ROUTE_TARGETS)
    # Largest remainder for other sizes, with stable route order breaking ties.
    shares = [size * weight for weight in STANDARD_ROUTE_TARGETS.values()]
    targets = [share // STANDARD_COHORT_SIZE for share in shares]
    for index in sorted(range(len(ROUTES)), key=lambda i: -(shares[i] % STANDARD_COHORT_SIZE))[:size - sum(targets)]:
        targets[index] += 1
    return dict(zip(ROUTES, targets))


def _inpatient_targets(size, sites):
    """IMH receives two shares and the rounding remainder; other sites one."""
    if "IMH" not in sites:
        return {}  # This preference only applies when IMH is eligible.
    baseline = size // (len(sites) - 1 + IMH_ALLOCATION_SHARES)
    return {site: size - (len(sites) - 1) * baseline if site == "IMH" else baseline
            for site in sites}


def _solve_priorities(model, objectives, variables, max_seconds):
    """Lock proven scores, not assignments; retain the last valid solution."""
    started = monotonic()
    deadline = started + max_seconds
    best = None
    stages = []
    status = cp_model.UNKNOWN
    for name, objective in objectives:
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        model.minimize(objective)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = remaining
        solver.parameters.num_search_workers = SOLVER_WORKERS
        solver.parameters.random_seed = SOLVER_RANDOM_SEED
        status = solver.solve(model)
        stages.append({"priority": name, "status": solver.status_name(status).lower()})
        if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            break
        best = solver
        score = solver.value(objective)
        stages[-1]["score"] = score
        if status != cp_model.OPTIMAL:
            break  # Never freeze an unproven score and optimise a lower priority.
        model.add(objective == score)
        model.clear_hints()
        for variable in variables:
            model.add_hint(variable, solver.value(variable))
    complete = len(stages) == len(objectives) and status == cp_model.OPTIMAL
    final_status = "optimal" if complete else "feasible" if best is not None else cp_model.CpSolver().status_name(status).lower()
    return best, final_status, stages, monotonic() - started


def draft_r1_schedule(workbook, reviewstore, max_seconds=DEFAULT_SOLVE_SECONDS):
    """Solve only R1 portions, including known mixed-year continuing residents.

    Schedule outstanding Medicine/Neuro before outstanding inpatient; ledger
    credit is retained regardless of historical timing or order. LOA pauses
    future blocks. Every available month is used until R1 completion; unfinished
    requirements carry forward rather than forcing completion by June.
    Soft preferences follow SOFT_PRIORITIES with one shared solving budget.
    Requests and excluded residents are not scheduled. Shared finite capacity
    with excluded residents requires review rather than a false capacity claim.
    """
    if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not isfinite(max_seconds) or max_seconds < 0:
        raise ValueError("max_seconds must be a finite nonnegative number")
    prepared = prepare_scheduler_inputs(workbook, reviewstore)
    selected = [p for p in prepared["residents"] if "r1" in p["recorded_years"]]
    excluded = [deepcopy({key: p[key] for key in ("name", "mcr", "source", "recorded_year")})
                for p in prepared["residents"] if "r1" not in p["recorded_years"]]
    result = {"scope": "r1_only", "status": "blocked", "residents": [], "excluded_residents": excluded,
              "selected_sources": [deepcopy(p["source"]) for p in selected], "blockers": [],
              "planning_months": deepcopy(prepared["planning_months"]), "cutoff": prepared["cutoff"], "basis": prepared["basis"],
              "limitations": ["R2-R5 portions are outside this draft", "Resident requests are not interpreted",
                              "Finite shared capacity with excluded residents requires review"],
              "soft_priority": list(SOFT_PRIORITIES)}
    blockers = result["blockers"]
    if not selected:
        blockers.append({"code": "no_r1_residents"})
    options = [o for o in prepared["catalogue_options"] if "r1" in recorded_years(o["residency_year"])]
    by_key = {}
    for option in options:
        blockers.extend({"code": code, "source": option["source"]} for code in option["reasons"])
        remarks = option["remarks"]
        inpatient = option["requirement_id"] == R1["Inpatient Psychiatry"]["id"]
        phase = "second" if inpatient else "first"
        phase_months = R1["Inpatient Psychiatry" if inpatient else "Medicine & Neurology"]["months"]
        expected_remark = f"To be completed in the {phase} {phase_months} months of R1"
        if remarks and remarks != expected_remark:
            blockers.append({"code": "unsupported_r1_remarks", "source": option["source"], "remarks": deepcopy(remarks)})
        key = (option["requirement_id"], option["institution"])
        if key in by_key:
            blockers.append({"code": "duplicate_r1_catalogue_option", "source": option["source"]})
        by_key[key] = option
    # No occupancy is silently reserved or ignored for residents outside this draft.
    finite = {normalized_label(o["label"]) for o in options if o["capacity"] is not None}
    catalogue = posting_catalogue(workbook["postings"])
    if finite:
        for person in workbook["residents"]:
            if "r1" in recorded_years(person.get("residency_year")):
                continue
            for posting in person["postings"]:
                if posting["status"] != "posting":
                    continue
                candidates = match_posting(posting, person.get("residency_year"), catalogue)["candidates"]
                if not candidates or any(normalized_label(c["label"]) in finite for c in candidates):
                    blockers.append({"code": "shared_capacity_outside_r1_scope", "source": posting["source"]})
    candidates, active_intake = [], []
    for person in selected:
        blockers.extend(deepcopy(person["blockers"]))
        incoming = person["recorded_years"] == ["r1"] and (person.get("intake") or "").strip() == prepared["planning_start"][:4]
        active_intake.append(incoming and any(m["available"] for m in person["availability"]))
        choices = []
        for route, remaining in _paths(person):
            if any(key not in by_key for key in remaining):
                continue
            schedule, consumed = [], 0
            for month in person["availability"]:
                if not month["available"] or consumed >= len(remaining):
                    schedule.append(None)
                else:
                    schedule.append(by_key[remaining[consumed]])
                    consumed += 1
            choices.append({"route": route, "schedule": schedule, "carryforward": Counter(remaining[consumed:]),
                            "credited_r1_months": R1_REQUIRED_MONTHS - len(remaining)})
        candidates.append(choices)
    if blockers:
        return result

    model = cp_model.CpModel()
    variables = [[model.new_bool_var(f"resident_{i}_path_{j}") for j in range(len(choices))]
                 for i, choices in enumerate(candidates)]
    for choices in variables:
        model.add_exactly_one(choices)  # Empty candidates correctly produce INFEASIBLE.
    occupancy = defaultdict(list)
    route_counts = defaultdict(list)
    ratio_counts = defaultdict(list)
    inpatient_counts = defaultdict(list)
    destination_penalties, cluster_penalties = [], []
    inpatient_id = R1["Inpatient Psychiatry"]["id"]
    for i, choices in enumerate(candidates):
        for j, choice in enumerate(choices):
            variable = variables[i][j]
            sites = {o["institution"] for o in choice["schedule"]
                     if o and o["requirement_id"] == inpatient_id}
            for site in sites:
                inpatient_counts[site].append(variable)
                if site not in PREFERRED_INPATIENT_SITES[choice["route"]]:
                    destination_penalties.append(variable)
            projected = cluster_coverage(selected[i]["months"] + [
                {"status": "expected", "requirement_year": "R1", "institution": o["institution"]}
                for o in choice["schedule"] if o])
            cluster_penalties.append(len(projected["missing"]) * variable)
            if active_intake[i]:
                route_counts[choice["route"]].append(variable)
            for month, option in enumerate(choice["schedule"]):
                if option is None:
                    continue
                occupancy[(month, option["requirement_id"], option["institution"])].append(variable)
                if option["requirement_id"] in {R1["General Medicine"]["id"], R1["Neurology"]["id"]}:
                    kind = "medicine" if option["requirement_id"] == R1["General Medicine"]["id"] else "neuro"
                    ratio_counts[(month, choice["route"], kind)].append(variable)
    for (month, requirement, institution), values in occupancy.items():
        capacity = by_key[(requirement, institution)]["capacity"]
        if capacity is not None:
            model.add(sum(values) <= capacity)
    targets = _targets(sum(active_intake))
    distribution_deviations, ratio_deviations = [], []
    for route, target in targets.items():
        deviation = model.new_int_var(0, len(selected), f"distribution_{route}")
        model.add_abs_equality(deviation, sum(route_counts[route]) - target)
        distribution_deviations.append(deviation)
    for month in range(len(prepared["planning_months"])):
        for route in PAIRED_ROUTES:
            deviation = model.new_int_var(0, MEDICINE_PER_NEUROLOGY * len(selected), f"ratio_{month}_{route}")
            model.add_abs_equality(deviation, sum(ratio_counts[(month, route, "medicine")]) - MEDICINE_PER_NEUROLOGY * sum(ratio_counts[(month, route, "neuro")]))
            ratio_deviations.append(deviation)
    singletons = {}
    for key, values in occupancy.items():
        flag = model.new_bool_var(f"singleton_{key}")
        model.add(sum(values) == 1).only_enforce_if(flag)
        model.add(sum(values) != 1).only_enforce_if(flag.Not())
        singletons[key] = flag
    inpatient_size = sum(any(any(o and o["requirement_id"] == inpatient_id for o in c["schedule"])
                             for c in choices) for choices in candidates)
    eligible_sites = sorted({o["institution"] for o in options
                             if o["requirement_id"] == inpatient_id and o["capacity"] != 0})
    inpatient_targets = _inpatient_targets(inpatient_size, eligible_sites)
    inpatient_deviations = []
    for site, target in inpatient_targets.items():
        deviation = model.new_int_var(0, len(selected), f"inpatient_deviation_{site}")
        model.add_abs_equality(deviation, sum(inpatient_counts[site]) - target)
        inpatient_deviations.append(deviation)
    objectives = list(zip(SOFT_PRIORITIES, (
        sum(distribution_deviations), sum(ratio_deviations), sum(singletons.values()),
        sum(inpatient_deviations), sum(destination_penalties), sum(cluster_penalties),
    )))
    solver, status, stages, elapsed = _solve_priorities(
        model, objectives, [v for choices in variables for v in choices], max_seconds)
    result.update(status=status, wall_time_seconds=elapsed, optimisation_stages=stages,
                  soft_targets={"active_incoming_cohort_size": sum(active_intake), "routes": targets,
                                "inpatient_residents": inpatient_size, "inpatient": inpatient_targets,
                                "smaller_cohort_policy": "largest_remainder_12_9_3_except_23_is_12_9_2"})
    if solver is None:
        return result
    actual_routes = Counter()
    ratios = []
    for i, person in enumerate(selected):
        choice = next(choice for j, choice in enumerate(candidates[i]) if solver.boolean_value(variables[i][j]))
        if active_intake[i]:
            actual_routes[choice["route"]] += 1
        months = []
        for availability, option in zip(person["availability"], choice["schedule"]):
            months.append({"month": availability["month"],
                           "status": "loa" if not availability["available"] else "posting" if option else "outside_r1_scope",
                           "label": option["label"] if option else None,
                           "target": deepcopy({key: option[key] for key in ("requirement_id", "institution", "source")}) if option else None})
        result["residents"].append({**deepcopy({key: person[key] for key in ("name", "mcr", "source", "slot_id", "recorded_year")}),
                                    "route": choice["route"], "months": months,
                                    "cluster_coverage": {
                                        "historical": deepcopy(person["cluster_coverage"]),
                                        "projected": cluster_coverage(person["months"] + [
                                            {"status": "expected", "requirement_year": option["residency_year"],
                                             "institution": option["institution"]}
                                            for option in choice["schedule"] if option is not None]),
                                    },
                                    "credited_r1_months": choice["credited_r1_months"],
                                    "carryforward": [{"requirement_id": requirement, "institution": institution, "months": months}
                                                     for (requirement, institution), months in choice["carryforward"].items()]})
    for month in range(len(prepared["planning_months"])):
        for route in PAIRED_ROUTES:
            medicine = sum(solver.boolean_value(v) for v in ratio_counts[(month, route, "medicine")])
            neuro = sum(solver.boolean_value(v) for v in ratio_counts[(month, route, "neuro")])
            ratios.append({"month": prepared["planning_months"][month]["month"], "route": route,
                           "medicine": medicine, "neurology": neuro, "deviation": abs(medicine - MEDICINE_PER_NEUROLOGY * neuro)})
    result["soft_results"] = {"route_counts": {route: actual_routes[route] for route in ROUTES},
                              "distribution_deviation": sum(solver.value(d) for d in distribution_deviations),
                              "monthly_ratios": ratios, "ratio_deviation": sum(item["deviation"] for item in ratios),
                              "inpatient_counts": {site: sum(solver.value(v) for v in values)
                                                   for site, values in inpatient_counts.items()},
                              "inpatient_deviation": solver.value(sum(inpatient_deviations)),
                              "destination_deviation": solver.value(sum(destination_penalties)),
                              "missing_clusters": solver.value(sum(cluster_penalties))}
    result["singletons"] = [
        {"month": prepared["planning_months"][month]["month"],
         "requirement_id": requirement, "institution": institution,
         "label": by_key[(requirement, institution)]["label"],
         "resident_source": deepcopy(person["source"])}
        for (month, requirement, institution), flag in singletons.items() if solver.value(flag)
        for person in result["residents"]
        if person["months"][month]["target"] is not None
        and (person["months"][month]["target"]["requirement_id"],
             person["months"][month]["target"]["institution"]) == (requirement, institution)]
    result["soft_results"]["singleton_months"] = len(result["singletons"])
    return result
