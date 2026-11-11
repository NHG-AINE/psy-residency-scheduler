"""Shared draft model and optimisation for R1-R5."""
from collections import defaultdict
from copy import deepcopy
from math import isfinite, gcd, floor
from time import monotonic
from threading import Event, Thread

from ortools.sat.python import cp_model

if __package__:
    from .request_preferences import resolve_requests, add_request_objective, unmet_request_reason, placement_fulfils_request
    from .cluster_coverage import CLUSTERS, cluster_coverage
    from .rules import r1_rules, r2_rules, r3_rules, r4_rules, r5_rules
    from .scheduler_inputs import prepare_scheduler_inputs
    from .workbook_import import match_posting, normalized_label, posting_catalogue, recorded_years
else:
    from request_preferences import resolve_requests, add_request_objective, unmet_request_reason, placement_fulfils_request
    from cluster_coverage import CLUSTERS, cluster_coverage
    from rules import r1_rules, r2_rules, r3_rules, r4_rules, r5_rules
    from scheduler_inputs import prepare_scheduler_inputs
    from workbook_import import match_posting, normalized_label, posting_catalogue, recorded_years


IMH_ALLOCATION_SHARES = 2

DEFAULT_SOLVE_SECONDS = 120
R1_RATIO_BOUND_SECONDS = 10
# Zero lets OR-Tools choose workers from the available CPUs.
SOLVER_WORKERS = 0
SOLVER_RANDOM_SEED = 0
CANCEL_POLL_SECONDS = 0.05


def _allocation_targets(size, sites):
    """IMH receives two shares and the rounding remainder; other sites one."""
    if "IMH" not in sites:
        return {}  # This preference only applies when IMH is eligible.
    baseline = size // (len(sites) - 1 + IMH_ALLOCATION_SHARES)
    return {site: size - (len(sites) - 1) * baseline if site == "IMH" else baseline
            for site in sites}


def _institution_balance(model, counts, maximum, name):
    """Prefer even site counts without choosing which site gets the remainder."""
    deviations = []
    for left in range(len(counts)):
        for right in range(left + 1, len(counts)):
            deviation = model.new_int_var(0, maximum, f"allocation_{name}_{left}_{right}")
            model.add_abs_equality(deviation, counts[left] - counts[right])
            deviations.append(deviation)
    return deviations


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


class _BestScoreTime(cp_model.CpSolverSolutionCallback):
    """Record the first observation of the best score, including presolve time."""
    def __init__(self):
        super().__init__()
        self.best_score = None
        self.best_time = None

    def on_solution_callback(self):
        score = self.objective_value
        if self.best_score is None or score < self.best_score:
            self.best_score = score
            self.best_time = self.wall_time


class DraftCancelled(Exception):
    pass


def _solve_priorities(model, objectives, variables, max_seconds, cancel=None, r1_ratio_data=None):
    """Lock proven scores, not assignments; retain the last valid solution."""
    started = monotonic()
    deadline = started + max_seconds
    best = None
    stages = []
    status = cp_model.UNKNOWN
    for name, objective in objectives:
        if cancel and cancel.is_set():
            raise DraftCancelled()
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        stage_started = monotonic()
        relaxation = None
        if (name == "monthly_medicine_neurology_ratio" and r1_ratio_data
                and stages and stages[-1]["priority"] == "incoming_route_distribution"
                and remaining > R1_RATIO_BOUND_SECONDS):
            bound_started = monotonic()
            small_model, small_objective, small_variables = r1_rules.ratio_relaxation(
                *r1_ratio_data, stages[-1]["score"])
            bound_budget = max(0, min(deadline, bound_started + R1_RATIO_BOUND_SECONDS) - monotonic())
            bound_solver, bound_status, bound_stages, _ = _solve_priorities(
                small_model, [("ratio_bound", small_objective)], small_variables, bound_budget, cancel)
            bound = floor(bound_stages[-1]["best_objective_bound"]) if bound_solver is not None else None
            if bound is not None:
                model.add(objective >= bound)
            relaxation = {"status": bound_status, "lower_bound": bound,
                          "wall_time_seconds": monotonic() - bound_started}
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
        model.minimize(objective)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = remaining
        solver.parameters.num_search_workers = SOLVER_WORKERS
        solver.parameters.random_seed = SOLVER_RANDOM_SEED
        callback = _BestScoreTime()
        finished = Event()
        def stop_when_cancelled():
            while not finished.wait(CANCEL_POLL_SECONDS):
                if cancel.is_set():
                    solver.stop_search()
        monitor = Thread(target=stop_when_cancelled, daemon=True) if cancel else None
        if monitor:
            monitor.start()
        try:
            status = solver.solve(model, callback)
        finally:
            finished.set()
            if monitor:
                monitor.join()
        if cancel and cancel.is_set():
            raise DraftCancelled()
        stages.append({"priority": name, "status": solver.status_name(status).lower(),
                       "wall_time_seconds": monotonic() - stage_started})
        if relaxation is not None:
            stages[-1]["ratio_relaxation"] = relaxation
        if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            break
        best = solver
        score = solver.value(objective)
        stages[-1]["score"] = score
        stages[-1]["best_objective_bound"] = solver.best_objective_bound
        if callback.best_time is not None:
            stages[-1]["best_score_time_seconds"] = callback.best_time + (relaxation["wall_time_seconds"] if relaxation else 0)
        if status != cp_model.OPTIMAL:
            break  # Never freeze an unproven score and optimise a lower priority.
        model.add(objective == score)
        model.clear_hints()
        for variable in variables:
            model.add_hint(variable, solver.value(variable))
    complete = len(stages) == len(objectives) and status == cp_model.OPTIMAL
    final_status = "optimal" if complete else "feasible" if best is not None else cp_model.CpSolver().status_name(status).lower()
    return best, final_status, stages, monotonic() - started


def draft_schedule(workbook, reviewstore, max_seconds=DEFAULT_SOLVE_SECONDS, cancel=None):
    """Schedule remaining R1 through R5 work in progression order.

    All years share capacity,
    soft priorities and one solve budget. Historical credit is preserved, LOA
    pauses blocks, and unfinished requirements carry beyond the planning year.
    """
    if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not isfinite(max_seconds) or max_seconds < 0:
        raise ValueError("max_seconds must be a finite nonnegative number")
    if cancel and cancel.is_set():
        raise DraftCancelled()
    prepared = prepare_scheduler_inputs(workbook, reviewstore)
    if cancel and cancel.is_set():
        raise DraftCancelled()
    years = {"r1", "r2", "r3", "r4", "r5"}
    selected = [p for p in prepared["residents"] if years & set(p["recorded_years"])]
    skipped = [deepcopy({**{key: p[key] for key in ("name", "mcr", "source", "recorded_year")},
                         "reasons": p["blockers"]}) for p in selected if p["blockers"]]
    selected = [p for p in selected if not p["blockers"]]
    excluded = [deepcopy({key: p[key] for key in ("name", "mcr", "source", "recorded_year")})
                for p in prepared["residents"] if not years & set(p["recorded_years"])]
    result = {"scope": "r1_r2_r3_r4_r5", "status": "blocked", "residents": [], "excluded_residents": excluded, "skipped_residents": skipped,
              "selected_sources": [deepcopy(p["source"]) for p in selected], "blockers": [],
              "planning_months": deepcopy(prepared["planning_months"]), "cutoff": prepared["cutoff"], "basis": prepared["basis"],
              "limitations": ["R5 electives with core-credit overlap or unsupported remarks are excluded", "Future posting availability and capacity are unknown",
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
    # A completed R3 resident may be awaiting a roster-year update.
    for person in selected:
        if cancel and cancel.is_set():
            raise DraftCancelled()
        if "r3" in person["recorded_years"] and "r4" not in person["recorded_years"]:
            required = [r for r in person["requirements"] if r["requirement_year"] in {"R2", "R3"}]
            r1_done = any(route["evidence_status"] == "supported" for route in person["r1_routes"])
            if r1_done and all(not r["remaining_months"] for r in required):
                person["recorded_years"].append("r4")
    has_r2 = any({"r2", "r3", "r4", "r5"} & set(person["recorded_years"]) for person in selected)
    r2_options = [o for o in prepared["catalogue_options"] if o["residency_year"] == "R2"] if has_r2 else []
    local_blockers = [[] for _ in selected]
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
            if {"r2", "r3", "r4", "r5"} & set(person["recorded_years"]):
                blocks[i] = r2_rules.prepare_blocks(person, r2_options, local_blockers[i])
        options += r2_options
    has_r3 = any({"r3", "r4", "r5"} & set(person["recorded_years"]) for person in selected)
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
        if {"r3", "r4", "r5"} & set(person["recorded_years"]):
            r3_blocks[i] = r3_rules.prepare_block(person, r3_options, local_blockers[i])
    options += r3_options
    r4_options = [o for o in prepared["catalogue_options"] if o["residency_year"] == "R4"] if any({"r4", "r5"} & set(p["recorded_years"]) for p in selected) else []
    seen_r4 = set()
    for o in r4_options:
        key = (o["requirement_id"], o["institution"], normalized_label(o["label"]))
        if key in seen_r4:
            blockers.append({"code": "duplicate_r4_catalogue_option", "source": o["source"]})
        seen_r4.add(key)
        blockers.extend({"code": code, "source": o["source"]} for code in o["reasons"])
        if o["remarks"]:
            blockers.append({"code": "unsupported_r4_remarks", "source": o["source"]})
    r4_blocks = [r4_rules.prepare_blocks(person, r4_options, prepared["planning_start"],
                     next(iter({r1_rules.R1_REQUIRED_MONTHS - c["credited_r1_months"] for c in candidates[i]}), 0)
                     + sum(r["remaining_months"] for r, _, _ in blocks[i] + r3_blocks[i]), local_blockers[i])
                 if {"r4", "r5"} & set(person["recorded_years"]) else [] for i, person in enumerate(selected)]
    options += r4_options
    r5_options = [o for o in prepared["catalogue_options"] if o["residency_year"] == "R5"] if any("r5" in p["recorded_years"] for p in selected) else []
    r5_options = [o for o in r5_options if r5_rules.supported_option(o)]
    seen_r5 = set()
    for o in r5_options:
        key = (o["requirement_id"], o["institution"], normalized_label(o["label"]))
        if key in seen_r5:
            blockers.append({"code": "duplicate_r5_catalogue_option", "source": o["source"]})
        seen_r5.add(key)
        blockers.extend({"code": code, "source": o["source"]} for code in o["reasons"])
    r5_blocks = [r5_rules.prepare_blocks(person, r5_options, prepared["planning_start"],
                     next(iter({r1_rules.R1_REQUIRED_MONTHS - c["credited_r1_months"] for c in candidates[i]}), 0)
                     + sum(r["remaining_months"] for r, _, _ in blocks[i] + r3_blocks[i] + r4_blocks[i]), local_blockers[i])
                 if "r5" in person["recorded_years"] else [] for i, person in enumerate(selected)]
    options += r5_options
    keep = [i for i, reasons in enumerate(local_blockers) if not reasons]
    for i, reasons in enumerate(local_blockers):
        if reasons:
            skipped.append({**{key: deepcopy(selected[i][key]) for key in ("name", "mcr", "source", "recorded_year")}, "reasons": reasons})
    if not keep and selected:
        blockers.extend(reason for reasons in local_blockers for reason in reasons)
    selected = [selected[i] for i in keep]
    candidates = [candidates[i] for i in keep]
    active_intake = [active_intake[i] for i in keep]
    blocks = [blocks[i] for i in keep]
    r3_blocks = [r3_blocks[i] for i in keep]
    r4_blocks = [r4_blocks[i] for i in keep]
    r5_blocks = [r5_blocks[i] for i in keep]
    result["selected_sources"] = [deepcopy(p["source"]) for p in selected]
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
    r4_monthly_totals = [0] * len(prepared["planning_months"])
    r5_demand = defaultdict(int)
    for i, person in enumerate(selected):
        if cancel and cancel.is_set():
            raise DraftCancelled()
        remaining = {r1_rules.R1_REQUIRED_MONTHS - c["credited_r1_months"] for c in candidates[i]}
        assert len(remaining) <= 1, "R1 candidates must have equal remaining duration"
        r1_months = next(iter(remaining), 0)
        placements.append(r2_rules.add_blocks(model, person, blocks[i], r1_months, i))
        # Every available training month is filled until remaining work ends.
        # Thus R2 occupancy is fixed even though block order/site are choices.
        active = [month for month, availability in enumerate(person["availability"]) if availability["available"]]
        r2_months = sum(r["remaining_months"] for r, _, _ in blocks[i])
        placements[-1] += r2_rules.add_blocks(model, person, r3_blocks[i], r1_months + r2_months, i)
        r3_months = sum(r["remaining_months"] for r, _, _ in r3_blocks[i])
        placements[-1] += r2_rules.add_blocks(model, person, r4_blocks[i], r1_months + r2_months + r3_months, i)
        for month in active[r1_months:r1_months + r2_months]:
            r2_monthly_totals[month] += 1
        r4_months = sum(r["remaining_months"] for r, _, _ in r4_blocks[i])
        for month in active[r1_months + r2_months + r3_months:r1_months + r2_months + r3_months + r4_months]:
            r4_monthly_totals[month] += 1
        r5_start = r1_months + r2_months + r3_months + r4_months
        placements[-1] += r2_rules.add_blocks(model, person, r5_blocks[i], r5_start, i)
        if len(active) > r5_start:
            for requirement, _, _ in r5_blocks[i]:
                r5_demand[requirement["requirement_id"]] += requirement["remaining_months"]
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
            visits += [p["variable"] for p in placements[i] if p["months"] and p["option"]["residency_year"] != "R5" and p["option"]["institution"] in sites]
            if {"r4", "r5"} & set(person["recorded_years"]):
                # Future R1-R4 choices witness feasibility only; they do
                # not contribute projected credit or reserve future capacity.
                future = [variables[i][j] for j, choice in enumerate(candidates[i])
                          if any(institution in sites for (_, institution) in choice["carryforward"])]
                future += [p["variable"] for p in placements[i]
                           if not p["months"] and p["option"]["residency_year"] != "R5" and p["option"]["institution"] in sites]
                model.add(sum(visits + future) >= 1)
            missing = model.new_bool_var(f"missing_{i}_{cluster}")
            model.add(sum(visits) == 0).only_enforce_if(missing)
            model.add(sum(visits) >= 1).only_enforce_if(missing.Not())
            if reaches_r3:
                r3_cluster_penalties.append(missing)
            elif not ({"r4", "r5"} & set(person["recorded_years"])):
                cluster_penalties.append(missing)
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
    if "IMH" not in eligible_sites:
        inpatient_deviations.extend(_institution_balance(
            model, [sum(inpatient_counts[site]) for site in eligible_sites], len(selected), "r1"))
    balance, allocation, r3_allocation, r4_allocation, r5_allocation = [], [], [], [], []
    r2_ids = sorted({r["requirement_id"] for bs in blocks for r, _, _ in bs})
    r4_ids = sorted({r["requirement_id"] for bs in r4_blocks for r, _, _ in bs})
    for month in range(len(prepared["planning_months"])):
        for year, ids, totals in (("r2", r2_ids, r2_monthly_totals), ("r4", r4_ids, r4_monthly_totals)):
            counts = [sum(sum(v) for (m, r, site, label), v in occupancy.items() if m == month and r == key) for key in ids]
            balance.extend(_posting_balance(model, counts, totals[month], f"{year}_{month}"))
    # R5 has 3/3/6-month requirements; normalise current remaining demand.
    divisor = 0
    for demand in r5_demand.values():
        divisor = gcd(divisor, demand)
    weights = {key: demand // divisor for key, demand in r5_demand.items()} if divisor else {}
    for month in range(len(prepared["planning_months"])):
        counts = {key: sum(sum(v) for (m, r, site, label), v in occupancy.items() if m == month and r == key) for key in weights}
        for left, a in enumerate(weights):
            for b in list(weights)[left + 1:]:
                bound = len(selected) * max(weights[a], weights[b])
                d = model.new_int_var(0, bound, f"r5_balance_{month}_{a}_{b}")
                model.add_abs_equality(d, counts[a] * weights[b] - counts[b] * weights[a])
                balance.append(d)
    # Allocation is per exact posting, not a shared bucket for all electives.
    allocation_groups = defaultdict(list)
    for ps in placements:
        for p in ps:
            if p["months"]:
                o = p["option"]
                allocation_groups[(o["requirement_id"], normalized_label(o["posting"]))].append(p)
    for group, ps in allocation_groups.items():
        eligible = sorted({o["institution"] for o in r2_options + r3_options + r4_options + r5_options if (o["requirement_id"], normalized_label(o["posting"])) == group and o["capacity"] != 0})
        if group[0].startswith(("r4.", "r5.")):
            eligible = sorted({p["option"]["institution"] for p in ps if p["option"]["capacity"] != 0})
        if len(eligible) < 2:
            continue
        if "IMH" not in eligible:
            counts = [sum(p["variable"] for p in ps if p["option"]["institution"] == site) for site in eligible]
            penalties = r5_allocation if group[0].startswith("r5.") else r4_allocation if group[0].startswith("r4.") else r3_allocation if group[0].startswith("r3.") else allocation
            penalties.extend(_institution_balance(model, counts, len(selected), group))
            continue
        total = sum(p["variable"] for p in ps)
        baseline = model.new_int_var(0, len(selected), f"baseline_{group}")
        model.add_division_equality(baseline, total, len(eligible) - 1 + IMH_ALLOCATION_SHARES)
        for site in eligible:
            target = total - (len(eligible) - 1) * baseline if site == "IMH" else baseline
            count = sum(p["variable"] for p in ps if p["option"]["institution"] == site)
            d = model.new_int_var(0, len(selected), f"allocation_{group}_{site}")
            model.add_abs_equality(d, count - target)
            (r5_allocation if group[0].startswith("r5.") else r4_allocation if group[0].startswith("r4.") else r3_allocation if group[0].startswith("r3.") else allocation).append(d)
    request_outcomes = [resolve_requests(person, prepared["requests"], options, prepared["planning_months"]) for person in selected]
    request_objective = add_request_objective(model, request_outcomes, placements)
    objectives = [
        ("incoming_route_distribution", preferences["distribution"]),
        ("monthly_medicine_neurology_ratio", preferences["ratio"]),
        ("posting_balance", sum(balance)),
        ("inpatient_allocation", sum(inpatient_deviations) + sum(allocation) + sum(r3_allocation) + sum(r4_allocation) + sum(r5_allocation)),
        ("inpatient_destination", preferences["destination"]),
        ("missing_clusters", sum(cluster_penalties)),
        ("singleton_months", sum(singletons.values())),
    ]
    if any(row['status'] == 'evaluable' and 'duplicate_of' not in row for rows in request_outcomes for row in rows):
        objectives.insert(2, ("resident_requests", request_objective))
    if r3_cluster_penalties:
        destination_index = next(i for i, (name, _) in enumerate(objectives) if name == "inpatient_destination")
        objectives.insert(destination_index, ("r3_missing_clusters", sum(r3_cluster_penalties)))
    result["soft_priority"] = [name for name, _ in objectives]
    solver, status, stages, elapsed = _solve_priorities(
        model, objectives, [v for choices in variables for v in choices] + [p["variable"] for ps in placements for p in ps], max_seconds, cancel,
        r1_ratio_data=(candidates, active_intake, prepared["planning_months"])
        if any(preferences["ratio_counts"].values()) else None)
    result.update(status=status, wall_time_seconds=elapsed, optimisation_stages=stages,
                  soft_targets={"active_incoming_cohort_size": sum(active_intake), "routes": preferences["targets"],
                                "inpatient_residents": inpatient_size, "inpatient": inpatient_targets,
                                "smaller_cohort_policy": "largest_remainder_12_9_3_except_23_is_12_9_2"})
    if solver is None:
        if status == "infeasible" and r4_options:
            blockers.append({"code": "r4_schedule_infeasible"})
            blockers.extend({"code": "r4_cluster_review", "source": p["source"], "clusters": p["cluster_coverage"]["missing"]}
                            for p in selected if {"r4", "r5"} & set(p["recorded_years"]) and p["cluster_coverage"]["missing"])
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
        outcomes = request_outcomes[i]
        for outcome in outcomes:
            if outcome.get('status') == 'evaluable' and 'duplicate_of' not in outcome:
                outcome['status'] = 'met' if solver.value(outcome.pop('_flag')) else 'not_met'
                if outcome['status'] == 'not_met':
                    outcome['reason_code'], outcome['reason'] = unmet_request_reason(
                        person, outcome, placements[i], options, stages)
                matching = [p for p in chosen if p['option']['requirement_id'] == outcome['requirement_id'] and p['months']]
                outcome['assigned'] = [
                    {'label': p['option']['label'],
                     'months': [prepared['planning_months'][m]['month'] for m in p['months']]}
                    for p in matching]
                # Display overlap uses the requested calendar window, even when
                # that window contains no valid start for the training block.
                requested_months = outcome['period_months']
                replacement = (outcome['status'] == 'not_met' and len(matching) == 1
                               and any(m in requested_months for m in matching[0]['months']))
                outcome['replacement_months'] = ([prepared['planning_months'][m]['month']
                                                   for m in matching[0]['months']] if replacement else [])
                outcome['matched_months'] = [
                    prepared['planning_months'][m]['month'] for p in matching
                    if outcome['status'] == 'met'
                    and placement_fulfils_request(p, outcome)
                    for m in p['months']]

        for outcome in outcomes:
            if 'duplicate_of' in outcome:
                original = outcomes[outcome['duplicate_of']]
                outcome.update({key: deepcopy(original[key]) for key in ('status', 'reason', 'reason_code', 'assigned', 'matched_months') if key in original})
        result["residents"].append({"requests": outcomes, **deepcopy({key: person[key] for key in ("name", "mcr", "source", "slot_id", "recorded_year")}),
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
        "r4_allocation_deviation": solver.value(sum(r4_allocation)),
        "r5_allocation_deviation": solver.value(sum(r5_allocation)),
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
