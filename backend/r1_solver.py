"""R1-only draft selection; no changes to uploaded postings or review decisions."""
from collections import Counter, defaultdict
from copy import deepcopy
from math import isfinite

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


ROUTES = ("TTSH/NNI", "SGH", "NUH")
R1 = PROGRAMME_REQUIREMENTS["R1"]


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
                if preferred_route in ROUTES[:2] and preferred_route != route:
                    continue
                for start in range(remaining[gm] + 1):
                    head = [(gm, medicine_site)] * start + [(neuro, neuro_site)] * remaining[neuro]
                    head += [(gm, medicine_site)] * (remaining[gm] - start)
                    yield route, head + tail
        if remaining[combined] == least_remaining:
            yield "NUH", [(combined, "NUH")] * remaining[combined] + tail


def _targets(size):
    if size == 23:
        return dict(zip(ROUTES, (12, 9, 2)))
    # Largest remainder for other sizes, with stable route order breaking ties.
    shares = [size * weight for weight in (12, 9, 3)]
    targets = [share // 24 for share in shares]
    for index in sorted(range(3), key=lambda i: -(shares[i] % 24))[:size - sum(targets)]:
        targets[index] += 1
    return dict(zip(ROUTES, targets))


def draft_r1_schedule(workbook, reviewstore, max_seconds=10):
    """Solve only R1 portions, including known mixed-year continuing residents.

    Schedule outstanding Medicine/Neuro before outstanding inpatient; ledger
    credit is retained regardless of historical timing or order. LOA pauses
    future blocks. Every available month is used until R1 completion; unfinished
    requirements carry forward rather than forcing completion by June.
    Soft priority: incoming institution distribution, then monthly 2:1 ratio.
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
              "soft_priority": ["incoming_route_distribution", "monthly_medicine_neurology_ratio"]}
    blockers = result["blockers"]
    if not selected:
        blockers.append({"code": "no_r1_residents"})
    options = [o for o in prepared["catalogue_options"] if "r1" in recorded_years(o["residency_year"])]
    by_key = {}
    for option in options:
        blockers.extend({"code": code, "source": option["source"]} for code in option["reasons"])
        remarks = option["remarks"]
        expected_remark = "To be completed in the " + ("second" if option["requirement_id"] == R1["Inpatient Psychiatry"]["id"] else "first") + " 6 months of R1"
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
                            "credited_r1_months": 12 - len(remaining)})
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
    for i, choices in enumerate(candidates):
        for j, choice in enumerate(choices):
            variable = variables[i][j]
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
        for route in ROUTES[:2]:
            deviation = model.new_int_var(0, 2 * len(selected), f"ratio_{month}_{route}")
            model.add_abs_equality(deviation, sum(ratio_counts[(month, route, "medicine")]) - 2 * sum(ratio_counts[(month, route, "neuro")]))
            ratio_deviations.append(deviation)
    # The ratio sum is at most 2 * residents * months, so this is exactly
    # lexicographic priority, not a guessed preference weight.
    ratio_bound = 2 * len(selected) * len(prepared["planning_months"])
    model.minimize(sum(distribution_deviations) * (ratio_bound + 1) + sum(ratio_deviations))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(max_seconds)
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    status = solver.solve(model)
    result.update(status=solver.status_name(status).lower(), wall_time_seconds=solver.wall_time,
                  soft_targets={"active_incoming_cohort_size": sum(active_intake), "routes": targets,
                                "smaller_cohort_policy": "largest_remainder_12_9_3_except_23_is_12_9_2"})
    if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
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
        for route in ROUTES[:2]:
            medicine = sum(solver.boolean_value(v) for v in ratio_counts[(month, route, "medicine")])
            neuro = sum(solver.boolean_value(v) for v in ratio_counts[(month, route, "neuro")])
            ratios.append({"month": prepared["planning_months"][month]["month"], "route": route,
                           "medicine": medicine, "neurology": neuro, "deviation": abs(medicine - 2 * neuro)})
    result["soft_results"] = {"route_counts": {route: actual_routes[route] for route in ROUTES},
                              "distribution_deviation": sum(solver.value(d) for d in distribution_deviations),
                              "monthly_ratios": ratios, "ratio_deviation": sum(item["deviation"] for item in ratios)}
    return result
