"""Shared draft model and optimisation; currently populated with R1 rules only."""
from collections import defaultdict
from copy import deepcopy
from math import isfinite
from time import monotonic

from ortools.sat.python import cp_model

if __package__:
    from .cluster_coverage import cluster_coverage
    from .rules import r1_rules
    from .scheduler_inputs import prepare_scheduler_inputs
    from .workbook_import import match_posting, normalized_label, posting_catalogue, recorded_years
else:
    from cluster_coverage import cluster_coverage
    from rules import r1_rules
    from scheduler_inputs import prepare_scheduler_inputs
    from workbook_import import match_posting, normalized_label, posting_catalogue, recorded_years


IMH_ALLOCATION_SHARES = 2

DEFAULT_SOLVE_SECONDS = 10
# Keep the search reproducible for a given set of inputs.
SOLVER_WORKERS = 1
SOLVER_RANDOM_SEED = 0


def _allocation_targets(size, sites):
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


def draft_schedule(workbook, reviewstore, max_seconds=DEFAULT_SOLVE_SECONDS):
    """Solve only R1 portions, including known mixed-year continuing residents.

    Schedule outstanding Medicine/Neuro before outstanding inpatient; ledger
    credit is retained regardless of historical timing or order. LOA pauses
    future blocks. Every available month is used until R1 completion; unfinished
    requirements carry forward rather than forcing completion by June.
    Soft preferences follow the R1 priority order with one shared solving budget.
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
              "soft_priority": list(r1_rules.SOFT_PRIORITIES)}
    blockers = result["blockers"]
    if not selected:
        blockers.append({"code": "no_r1_residents"})
    options = [o for o in prepared["catalogue_options"] if "r1" in recorded_years(o["residency_year"])]
    by_key, candidates, active_intake = r1_rules.prepare_candidates(
        selected, options, prepared["planning_start"], blockers)
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
                matches = match_posting(posting, person.get("residency_year"), catalogue)["candidates"]
                if not matches or any(normalized_label(c["label"]) in finite for c in matches):
                    blockers.append({"code": "shared_capacity_outside_r1_scope", "source": posting["source"]})
    if blockers:
        return result

    model = cp_model.CpModel()
    variables = [[model.new_bool_var(f"resident_{i}_path_{j}") for j in range(len(choices))]
                 for i, choices in enumerate(candidates)]
    for choices in variables:
        model.add_exactly_one(choices)  # Empty candidates correctly produce INFEASIBLE.
    occupancy = defaultdict(list)
    inpatient_counts = defaultdict(list)
    cluster_penalties = []
    inpatient_id = r1_rules.R1["Inpatient Psychiatry"]["id"]
    for i, choices in enumerate(candidates):
        for j, choice in enumerate(choices):
            variable = variables[i][j]
            sites = {o["institution"] for o in choice["schedule"]
                     if o and o["requirement_id"] == inpatient_id}
            for site in sites:
                inpatient_counts[site].append(variable)
            projected = cluster_coverage(selected[i]["months"] + [
                {"status": "expected", "requirement_year": o["residency_year"], "institution": o["institution"]}
                for o in choice["schedule"] if o])
            cluster_penalties.append(len(projected["missing"]) * variable)
            for month, option in enumerate(choice["schedule"]):
                if option is None:
                    continue
                occupancy[(month, option["requirement_id"], option["institution"])].append(variable)
    for (month, requirement, institution), values in occupancy.items():
        capacity = by_key[(requirement, institution)]["capacity"]
        if capacity is not None:
            model.add(sum(values) <= capacity)
    preferences = r1_rules.add_preferences(model, candidates, variables, active_intake, prepared["planning_months"])
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
    inpatient_targets = _allocation_targets(inpatient_size, eligible_sites)
    inpatient_deviations = []
    for site, target in inpatient_targets.items():
        deviation = model.new_int_var(0, len(selected), f"inpatient_deviation_{site}")
        model.add_abs_equality(deviation, sum(inpatient_counts[site]) - target)
        inpatient_deviations.append(deviation)
    objectives = list(zip(r1_rules.SOFT_PRIORITIES, (
        preferences["distribution"], preferences["ratio"], sum(singletons.values()),
        sum(inpatient_deviations), preferences["destination"], sum(cluster_penalties),
    )))
    solver, status, stages, elapsed = _solve_priorities(
        model, objectives, [v for choices in variables for v in choices], max_seconds)
    result.update(status=status, wall_time_seconds=elapsed, optimisation_stages=stages,
                  soft_targets={"active_incoming_cohort_size": sum(active_intake), "routes": preferences["targets"],
                                "inpatient_residents": inpatient_size, "inpatient": inpatient_targets,
                                "smaller_cohort_policy": "largest_remainder_12_9_3_except_23_is_12_9_2"})
    if solver is None:
        return result
    for i, person in enumerate(selected):
        choice = next(choice for j, choice in enumerate(candidates[i]) if solver.boolean_value(variables[i][j]))
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
    result["soft_results"] = {
        **r1_rules.preference_results(solver, preferences, prepared["planning_months"]),
        "inpatient_counts": {site: sum(solver.value(v) for v in values) for site, values in inpatient_counts.items()},
        "inpatient_deviation": solver.value(sum(inpatient_deviations)),
        "missing_clusters": solver.value(sum(cluster_penalties)),
    }
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
