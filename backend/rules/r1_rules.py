"""R1 candidate schedules and preferences, added to the shared scheduling model."""
from collections import Counter, defaultdict
from copy import deepcopy

if __package__ == "backend.rules":
    from ..programme_requirements import PROGRAMME_REQUIREMENTS
else:
    from programme_requirements import PROGRAMME_REQUIREMENTS


STANDARD_ROUTE_TARGETS = {"TTSH/NNI": 12, "SGH": 9, "NUH": 3}
SHORT_COHORT_ROUTE_TARGETS = {"TTSH/NNI": 12, "SGH": 9, "NUH": 2}
STANDARD_COHORT_SIZE = sum(STANDARD_ROUTE_TARGETS.values())
SHORT_COHORT_SIZE = sum(SHORT_COHORT_ROUTE_TARGETS.values())
ROUTES = tuple(STANDARD_ROUTE_TARGETS)
PAIRED_ROUTES = ("TTSH/NNI", "SGH")
MEDICINE_PER_NEUROLOGY = 2
PREFERRED_INPATIENT_SITES = {
    "TTSH/NNI": {"SGH", "CGH", "NUH"},
    "SGH": {"IMH", "TTSH", "NUH"},
    "NUH": {"IMH", "TTSH", "SGH", "CGH"},
}
SOFT_PRIORITIES = (
    "incoming_route_distribution", "monthly_medicine_neurology_ratio",
    "singleton_months", "inpatient_allocation", "inpatient_destination", "missing_clusters",
)

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


def prepare_candidates(selected, options, planning_start, blockers):
    """Build only remaining R1 work; LOA pauses each candidate's sequence."""
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
    candidates, active_intake = [], []
    for person in selected:
        blockers.extend(deepcopy(person["blockers"]))
        incoming = person["recorded_years"] == ["r1"] and (person.get("intake") or "").strip() == planning_start[:4]
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
    return by_key, candidates, active_intake


def add_preferences(model, candidates, variables, active_intake, planning_months):
    """R1-only route, monthly ratio and route-to-inpatient preferences."""
    route_counts, ratio_counts = defaultdict(list), defaultdict(list)
    destination_penalties = []
    for i, choices in enumerate(candidates):
        for j, choice in enumerate(choices):
            variable = variables[i][j]
            if active_intake[i]:
                route_counts[choice["route"]].append(variable)
            sites = {o["institution"] for o in choice["schedule"]
                     if o and o["requirement_id"] == R1["Inpatient Psychiatry"]["id"]}
            for site in sites:
                if site not in PREFERRED_INPATIENT_SITES[choice["route"]]:
                    destination_penalties.append(variable)
            for month, option in enumerate(choice["schedule"]):
                if option and option["requirement_id"] in {R1["General Medicine"]["id"], R1["Neurology"]["id"]}:
                    kind = "medicine" if option["requirement_id"] == R1["General Medicine"]["id"] else "neuro"
                    ratio_counts[(month, choice["route"], kind)].append(variable)
    targets = _targets(sum(active_intake))
    distribution_deviations, ratio_deviations = [], []
    for route, target in targets.items():
        deviation = model.new_int_var(0, len(candidates), f"distribution_{route}")
        model.add_abs_equality(deviation, sum(route_counts[route]) - target)
        distribution_deviations.append(deviation)
    for month in range(len(planning_months)):
        for route in PAIRED_ROUTES:
            deviation = model.new_int_var(0, MEDICINE_PER_NEUROLOGY * len(candidates), f"ratio_{month}_{route}")
            model.add_abs_equality(deviation, sum(ratio_counts[(month, route, "medicine")]) - MEDICINE_PER_NEUROLOGY * sum(ratio_counts[(month, route, "neuro")]))
            ratio_deviations.append(deviation)
    return {"targets": targets, "route_counts": route_counts, "ratio_counts": ratio_counts,
            "distribution": sum(distribution_deviations), "ratio": sum(ratio_deviations),
            "destination": sum(destination_penalties)}


def preference_results(solver, preferences, planning_months):
    ratios = []
    for month in range(len(planning_months)):
        for route in PAIRED_ROUTES:
            medicine = sum(solver.value(v) for v in preferences["ratio_counts"][(month, route, "medicine")])
            neuro = sum(solver.value(v) for v in preferences["ratio_counts"][(month, route, "neuro")])
            ratios.append({"month": planning_months[month]["month"], "route": route,
                           "medicine": medicine, "neurology": neuro, "deviation": abs(medicine - MEDICINE_PER_NEUROLOGY * neuro)})
    return {"route_counts": {route: sum(solver.value(v) for v in preferences["route_counts"][route]) for route in ROUTES},
            "distribution_deviation": solver.value(preferences["distribution"]),
            "monthly_ratios": ratios, "ratio_deviation": solver.value(preferences["ratio"]),
            "destination_deviation": solver.value(preferences["destination"])}
