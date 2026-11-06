"""Shared draft model and optimisation for R1-R3."""
from collections import defaultdict
from copy import deepcopy
from math import isfinite
from time import monotonic

from ortools.sat.python import cp_model

if __package__:
    from .cluster_coverage import CLUSTERS, cluster_coverage
    from .rules import r1_rules, r2_rules, r3_rules
    from .scheduler_inputs import prepare_scheduler_inputs
    from .workbook_import import match_posting, normalized_label, posting_catalogue, recorded_years
else:
    from cluster_coverage import CLUSTERS, cluster_coverage
    from rules import r1_rules, r2_rules, r3_rules
    from scheduler_inputs import prepare_scheduler_inputs
    from workbook_import import match_posting, normalized_label, posting_catalogue, recorded_years


IMH_ALLOCATION_SHARES = 2

DEFAULT_SOLVE_SECONDS = 40
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


def _posting_balance(model, counts, total, month):
    """Pairwise imbalance with a valid lower bound, not an equal-split quota."""
    model.add(sum(counts) == total)
    deviations = []
    for i, left in enumerate(counts):
        for right in counts[i + 1:]:
            deviation = model.new_int_var(0, total, f"balance_{month}_{len(deviations)}")
            model.add_abs_equality(deviation, left - right)
            deviations.append(deviation)
    if counts:
        # An even integer split has r larger groups and K-r smaller groups.
        # Only those r*(K-r) pairs differ, by one each. Eligibility/capacity
        # may force a higher score; this bound never forces the ideal split.
        remainder = total % len(counts)
        model.add(sum(deviations) >= remainder * (len(counts) - remainder))
    return deviations


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
        stage_started = monotonic()
        status = solver.solve(model)
        stages.append({"priority": name, "status": solver.status_name(status).lower(),
                       "wall_time_seconds": monotonic() - stage_started})
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
    """Schedule remaining R1, R2 and R3 work in progression order.

    All years share capacity,
    soft priorities and one solve budget. Historical credit is preserved, LOA
    pauses blocks, and unfinished requirements carry beyond the planning year.
    """
    if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not isfinite(max_seconds) or max_seconds < 0:
        raise ValueError("max_seconds must be a finite nonnegative number")
    prepared = prepare_scheduler_inputs(workbook, reviewstore)
    years = {"r1", "r2", "r3"}
    selected = [p for p in prepared["residents"] if years & set(p["recorded_years"])]
    skipped = [deepcopy({**{key: p[key] for key in ("name", "mcr", "source", "recorded_year")},
                         "reasons": p["blockers"]}) for p in selected if p["blockers"]]
    selected = [p for p in selected if not p["blockers"]]
    excluded = [deepcopy({key: p[key] for key in ("name", "mcr", "source", "recorded_year")})
                for p in prepared["residents"] if not years & set(p["recorded_years"])]
    result = {"scope": "r1_r2_r3", "status": "blocked", "residents": [], "excluded_residents": excluded, "skipped_residents": skipped,
              "selected_sources": [deepcopy(p["source"]) for p in selected], "blockers": [],
              "planning_months": deepcopy(prepared["planning_months"]), "cutoff": prepared["cutoff"], "basis": prepared["basis"],
              "limitations": ["R4-R5 portions are outside this draft", "Resident requests are not interpreted",
                              "Finite shared capacity with excluded residents requires review"],
              "soft_priority": list(r1_rules.SOFT_PRIORITIES)}
    blockers = result["blockers"]
    if not selected:
        blockers.extend(reason for person in skipped for reason in person["reasons"])
        if not skipped:
            blockers.append({"code": "no_schedulable_residents"})
    options = [o for o in prepared["catalogue_options"] if "r1" in recorded_years(o["residency_year"])]
    by_key, candidates, active_intake = r1_rules.prepare_candidates(
        selected, options, prepared["planning_start"], blockers)
    has_r2 = any({"r2", "r3"} & set(person["recorded_years"]) for person in selected)
    r2_options = [o for o in prepared["catalogue_options"] if o["residency_year"] == "R2"] if has_r2 else []
    blocks = [[] for _ in selected]
    if has_r2:
        seen_r2 = set()
        for o in r2_options:
            key = (o["requirement_id"], o["institution"], normalized_label(o["label"]))
            if key in seen_r2:
                blockers.append({"code": "duplicate_r2_catalogue_option", "source": o["source"]})
            seen_r2.add(key)
            blockers.extend({"code": code, "source": o["source"]} for code in o["reasons"])
            remarks = o["remarks"]
            if remarks and not (isinstance(remarks, list) and all(r["text"].strip().lower() == "(3 months duration)" for r in remarks)):
                blockers.append({"code": "unsupported_r2_remarks", "source": o["source"]})
        for summary in prepared["catalogue_summaries"]:
            if summary.get("residency_year") == "R2" and summary.get("remarks"):
                blockers.append({"code": "unsupported_r2_remarks", "source": summary["source"]})
        for i, person in enumerate(selected):
            if {"r2", "r3"} & set(person["recorded_years"]):
                blocks[i] = r2_rules.prepare_blocks(person, r2_options, blockers)
        options += r2_options
    has_r3 = any("r3" in person["recorded_years"] for person in selected)
    r3_options = [o for o in prepared["catalogue_options"] if o["residency_year"] == "R3"] if has_r3 else []
    r3_blocks = [[] for _ in selected]
    seen_r3 = set()
    for o in r3_options:
        key = (o["requirement_id"], o["institution"], normalized_label(o["label"]))
        if key in seen_r3:
            blockers.append({"code": "duplicate_r3_catalogue_option", "source": o["source"]})
        seen_r3.add(key)
        blockers.extend({"code": code, "source": o["source"]} for code in o["reasons"])
        if o["remarks"]:
            blockers.append({"code": "unsupported_r3_remarks", "source": o["source"]})
    for i, person in enumerate(selected):
        if "r3" in person["recorded_years"]:
            remaining = {r1_rules.R1_REQUIRED_MONTHS - c["credited_r1_months"] for c in candidates[i]}
            earlier = next(iter(remaining), 0) + sum(r["remaining_months"] for r, _, _ in blocks[i])
            r3_blocks[i] = r3_rules.prepare_block(person, r3_options, prepared["planning_start"], earlier, blockers)
    options += r3_options
    by_key = {(o["requirement_id"], o["institution"], o["label"]): o for o in options}
    # No occupancy is silently reserved or ignored for residents outside this draft.
    finite = {(o["category"], o["residency_year"], normalized_label(o["label"]))
              for o in options if o["capacity"] is not None}
    catalogue = posting_catalogue(workbook["postings"])
    if finite:
        for person in workbook["residents"]:
            if any(person["source"] == scheduled["source"] for scheduled in selected):
                continue
            for posting in person["postings"]:
                if posting["status"] != "posting":
                    continue
                match = match_posting(posting, person.get("residency_year"), catalogue)
                matches = [match["selected_candidate"]] if match.get("selected_candidate") else match["candidates"]
                if not matches or any((c["category"], c["residency_year"], normalized_label(c["label"])) in finite for c in matches):
                    blockers.append({"code": "shared_capacity_outside_draft_scope", "source": posting["source"]})
    if blockers:
        return result

    model = cp_model.CpModel()
    variables = [[model.new_bool_var(f"resident_{i}_path_{j}") for j in range(len(choices))]
                 for i, choices in enumerate(candidates)]
    for choices in variables:
        model.add_exactly_one(choices)  # Empty candidates correctly produce INFEASIBLE.
    occupancy = defaultdict(list)
    inpatient_counts = defaultdict(list)
    inpatient_id = r1_rules.R1["Inpatient Psychiatry"]["id"]
    for i, choices in enumerate(candidates):
        for j, choice in enumerate(choices):
            variable = variables[i][j]
            sites = {o["institution"] for o in choice["schedule"]
                     if o and o["requirement_id"] == inpatient_id}
            for site in sites:
                inpatient_counts[site].append(variable)
            for month, option in enumerate(choice["schedule"]):
                if option is None:
                    continue
                occupancy[(month, option["requirement_id"], option["institution"], option["label"])].append(variable)
    placements = []
    r2_monthly_totals = [0] * len(prepared["planning_months"])
    for i, person in enumerate(selected):
        remaining = {r1_rules.R1_REQUIRED_MONTHS - c["credited_r1_months"] for c in candidates[i]}
        assert len(remaining) <= 1, "R1 candidates must have equal remaining duration"
        r1_months = next(iter(remaining), 0)
        placements.append(r2_rules.add_blocks(model, person, blocks[i], r1_months, i))
        # Every available training month is filled until remaining work ends.
        # Thus R2 occupancy is fixed even though block order/site are choices.
        active = [month for month, availability in enumerate(person["availability"]) if availability["available"]]
        r2_months = sum(r["remaining_months"] for r, _, _ in blocks[i])
        placements[-1] += r2_rules.add_blocks(model, person, r3_blocks[i], r1_months + r2_months, i)
        for month in active[r1_months:r1_months + r2_months]:
            r2_monthly_totals[month] += 1
        for placement in placements[-1]:
            o = placement["option"]
            for month in placement["months"]:
                occupancy[(month, o["requirement_id"], o["institution"], o["label"])].append(placement["variable"])
    cluster_penalties, r3_cluster_penalties = [], []
    for i, person in enumerate(selected):
        reaches_r3 = any(p["months"] and p["option"]["residency_year"] == "R3" for p in placements[i])
        for cluster, sites in CLUSTERS.items():
            if cluster in person["cluster_coverage"]["visited"]:
                continue
            visits = [variables[i][j] for j, c in enumerate(candidates[i]) if any(o and o["institution"] in sites for o in c["schedule"])]
            visits += [p["variable"] for p in placements[i] if p["months"] and p["option"]["institution"] in sites]
            missing = model.new_bool_var(f"missing_{i}_{cluster}")
            model.add(sum(visits) == 0).only_enforce_if(missing)
            model.add(sum(visits) >= 1).only_enforce_if(missing.Not())
            (r3_cluster_penalties if reaches_r3 else cluster_penalties).append(missing)
    for (month, requirement, institution, label), values in occupancy.items():
        capacity = by_key[(requirement, institution, label)]["capacity"]
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
    balance, allocation, r3_allocation = [], [], []
    r2_ids = sorted({r["requirement_id"] for bs in blocks for r, _, _ in bs})
    for month in range(len(prepared["planning_months"])):
        counts = [sum(sum(v) for (m, r, site, label), v in occupancy.items() if m == month and r == key) for key in r2_ids]
        balance.extend(_posting_balance(model, counts, r2_monthly_totals[month], month))
    # Allocation is per exact posting, not a shared bucket for all electives.
    allocation_groups = defaultdict(list)
    for ps in placements:
        for p in ps:
            if p["months"]:
                o = p["option"]
                allocation_groups[(o["requirement_id"], normalized_label(o["posting"]))].append(p)
    for group, ps in allocation_groups.items():
        eligible = sorted({o["institution"] for o in r2_options + r3_options if (o["requirement_id"], normalized_label(o["posting"])) == group and o["capacity"] != 0})
        if "IMH" not in eligible:
            continue
        total = sum(p["variable"] for p in ps)
        baseline = model.new_int_var(0, len(selected), f"baseline_{group}")
        model.add_division_equality(baseline, total, len(eligible) - 1 + IMH_ALLOCATION_SHARES)
        for site in eligible:
            target = total - (len(eligible) - 1) * baseline if site == "IMH" else baseline
            count = sum(p["variable"] for p in ps if p["option"]["institution"] == site)
            d = model.new_int_var(0, len(selected), f"allocation_{group}_{site}")
            model.add_abs_equality(d, count - target)
            (r3_allocation if group[0].startswith("r3.") else allocation).append(d)
    objectives = [
        ("incoming_route_distribution", preferences["distribution"]),
        ("monthly_medicine_neurology_ratio", preferences["ratio"]),
        ("posting_balance", sum(balance)),
        ("singleton_months", sum(singletons.values())),
        ("inpatient_allocation", sum(inpatient_deviations) + sum(allocation) + sum(r3_allocation)),
        ("inpatient_destination", preferences["destination"]),
        ("missing_clusters", sum(cluster_penalties)),
    ]
    if r3_cluster_penalties:
        objectives.insert(5, ("r3_missing_clusters", sum(r3_cluster_penalties)))
    result["soft_priority"] = [name for name, _ in objectives]
    solver, status, stages, elapsed = _solve_priorities(
        model, objectives, [v for choices in variables for v in choices] + [p["variable"] for ps in placements for p in ps], max_seconds)
    result.update(status=status, wall_time_seconds=elapsed, optimisation_stages=stages,
                  soft_targets={"active_incoming_cohort_size": sum(active_intake), "routes": preferences["targets"],
                                "inpatient_residents": inpatient_size, "inpatient": inpatient_targets,
                                "smaller_cohort_policy": "largest_remainder_12_9_3_except_23_is_12_9_2"})
    if solver is None:
        return result
    for i, person in enumerate(selected):
        choice = next(choice for j, choice in enumerate(candidates[i]) if solver.boolean_value(variables[i][j]))
        choice = deepcopy(choice)
        chosen = [p for p in placements[i] if solver.value(p["variable"])]
        for placement in chosen:
            for month in placement["months"]:
                assert choice["schedule"][month] is None
                choice["schedule"][month] = placement["option"]
        months = []
        for availability, option in zip(person["availability"], choice["schedule"]):
            months.append({"month": availability["month"],
                           "status": "loa" if not availability["available"] else "posting" if option else "outside_draft_scope",
                           "label": option["label"] if option else None,
                           "target": deepcopy({key: option[key] for key in ("requirement_id", "institution", "source", "category", "residency_year", "label")}) if option else None})
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
                                                     for (requirement, institution), months in choice["carryforward"].items()]
                                    + [{"requirement_id": p["option"]["requirement_id"], "institution": p["option"]["institution"],
                                        "label": p["option"]["label"], "months": p["remaining"]} for p in chosen if p["remaining"]]})
    result["soft_results"] = {
        **r1_rules.preference_results(solver, preferences, prepared["planning_months"]),
        "inpatient_counts": {site: sum(solver.value(v) for v in values) for site, values in inpatient_counts.items()},
        "inpatient_deviation": solver.value(sum(inpatient_deviations)),
        "missing_clusters": solver.value(sum(cluster_penalties) + sum(r3_cluster_penalties)),
        "r3_missing_clusters": solver.value(sum(r3_cluster_penalties)),
        "posting_balance": solver.value(sum(balance)), "r2_allocation_deviation": solver.value(sum(allocation)),
        "r3_allocation_deviation": solver.value(sum(r3_allocation)),
    }
    result["singletons"] = [
        {"month": prepared["planning_months"][month]["month"],
         "requirement_id": requirement, "institution": institution,
         "label": by_key[(requirement, institution, label)]["label"],
         "resident_source": deepcopy(person["source"])}
        for (month, requirement, institution, label), flag in singletons.items() if solver.value(flag)
        for person in result["residents"]
        if person["months"][month]["target"] is not None
        and (person["months"][month]["target"]["requirement_id"],
             person["months"][month]["target"]["institution"]) == (requirement, institution) and person["months"][month]["label"] == label]
    result["soft_results"]["singleton_months"] = len(result["singletons"])
    return result
