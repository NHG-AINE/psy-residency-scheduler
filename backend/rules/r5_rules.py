"""R5 core routes and six-month or paired three-month elective blocks."""
import re
from .r2_rules import partial_posting_identity, add_blocks

if __package__ == "backend.rules":
    from ..requirement_ledger import month_number, r5_elective_runs
    from ..programme_requirements import PROGRAMME_REQUIREMENTS, additional_r5_credit
else:
    from requirement_ledger import month_number, r5_elective_runs
    from programme_requirements import PROGRAMME_REQUIREMENTS, additional_r5_credit


COMBINED = PROGRAMME_REQUIREMENTS["R5"]["Child and Geriatric Psychiatry"]


def elective_durations(option):
    """Respect structured lengths and keep options with unsupported notes out of drafts."""
    additional_credit = additional_r5_credit(option)
    durations = {3, 6}
    for remark in option.get("remarks") or []:
        note = remark["text"].strip().casefold()
        if additional_credit and re.fullmatch(r"\(which will meet the core \d+ months (?:of )?r5 [a-z &]+ requirements\)", note):
            continue  # The structured fields specify credit; these notes describe it.
        if note == "(team-based continuity of care)":
            continue  # Informational; every elective block already keeps its posting/site.
        if note == "(all required 6 months duration)":
            durations &= {6}
        elif re.fullmatch(r"\(3 months\s*-\s*that can be paired with any other institution\)", note):
            durations &= {3}
        else:
            return ()
    for duration in re.findall(r"\(\s*([36]) months\s*\)", option["label"], re.IGNORECASE):
        durations &= {int(duration)}
    lengths = option.get("allowed_block_lengths")
    if lengths is not None:
        return tuple(lengths) if set(lengths) <= durations else ()
    return tuple(sorted(durations))


def supported_option(option):
    return bool(elective_durations(option)) if option["category"] == "elective" else not option["remarks"]


def elective_routes(person, options, planning_start, earlier_months, blockers, allow_split=False):
    requirement = next((r for r in person["requirements"] if r["requirement_id"] == "r5.elective"), None)
    if requirement is None or not requirement["remaining_months"]:
        return [[]]  # Completed historical credit is not reinterpreted as new blocks.
    runs = r5_elective_runs(person['months'])

    def continues(run):
        expected = run["start"]
        for month in person["months"]:
            number = month_number(month["month"])
            if number < run["start"]:
                continue
            if number != expected or not (month["status"] == "loa" or
                    month["status"] == "expected" and month.get("requirement_id") == "r5.elective"
                    and (month["posting"], month["institution"]) == run["identity"]):
                return False
            expected += 1
        return not earlier_months and expected == month_number(planning_start)

    routes, missing = [], False
    # Historical block obligations survive even when the old request is absent.
    for durations in ((6,), (3, 3)) if allow_split or runs else ((6,),):
        if len(runs) > len(durations) or any(run["count"] > duration for run, duration in zip(runs, durations)):
            continue
        if any(run["count"] < durations[i] and (i != len(runs) - 1 or not continues(run))
               for i, run in enumerate(runs)):
            continue
        route = []
        for index, duration in enumerate(durations):
            run = runs[index] if index < len(runs) else None
            credited = run["count"] if run else 0
            eligible = [o for o in options if o["requirement_id"] == "r5.elective"
                        and duration in elective_durations(o)
                        and (run is None or (o["posting"], o["institution"]) == run["identity"])]
            if not eligible:
                missing = True
                break
            if credited == duration:
                continue
            block = {**requirement, "block_id": f"r5.elective.{index}", "required_months": duration,
                     "expected_months": credited, "remaining_months": duration - credited}
            route.append((block, eligible, bool(credited)))
        else:
            routes.append(route)
    if not routes:
        blockers.append({"code": "missing_r5_catalogue_option" if missing else "conflicting_partial_r5_history",
                         "source": person["source"], "requirement_id": "r5.elective"})
    return routes


def prepare_blocks(person, options, planning_start, earlier_months, blockers):
    blocks = []
    for requirement in person["requirements"]:
        if (requirement["requirement_year"] != "R5" or requirement["requirement_id"] == "r5.elective"
                or not requirement["remaining_months"]):
            continue
        key = requirement["requirement_id"]
        try:
            partial = partial_posting_identity(person, key)
        except ValueError:
            blockers.append({"code": "conflicting_partial_r5_history", "source": person["source"]})
            continue
        if partial:
            history = [m for m in person["months"] if m["status"] == "expected" and m.get("requirement_id") == key]
            first = month_number(history[0]["month"])
            tail = [m for m in person["months"] if month_number(m["month"]) >= first]
            expected = first
            for month in tail:
                if month_number(month["month"]) != expected or not (
                        month["status"] == "loa" or month["status"] == "expected" and month.get("requirement_id") == key):
                    break
                expected += 1
            if earlier_months or expected != month_number(planning_start):
                blockers.append({"code": "conflicting_partial_r5_history", "source": person["source"]})
                continue
        eligible = [o for o in options if o["requirement_id"] == key
                    and (partial is None or (o["posting"], o["institution"]) == partial)]
        if not eligible:
            blockers.append({"code": "missing_r5_catalogue_option", "source": person["source"], "requirement_id": key})
        blocks.append((requirement, eligible, partial is not None))
    if sum(partial for _, _, partial in blocks) > 1:
        blockers.append({"code": "conflicting_partial_r5_history", "source": person["source"]})
    return blocks


def prepare_routes(person, options, planning_start, earlier_months, blockers, allow_split=False):
    """Combine supported core alternatives with one six or two three-month electives."""
    electives = elective_routes(person, options, planning_start, earlier_months, blockers, allow_split)
    if not electives:
        return []
    requirements = {r["requirement_id"]: r for r in person["requirements"]}
    combined = requirements[COMBINED["id"]]
    partial_combined = combined["expected_months"] and combined["remaining_months"]
    separate_started = any(requirements[key]["expected_months"] for key in COMBINED["credits"])
    route_ids = []
    if not partial_combined:
        route_ids.append(set(COMBINED["credits"]))
    if combined["remaining_months"] and (partial_combined or not separate_started) and any(
            o["requirement_id"] == COMBINED["id"] for o in options):
        route_ids.append({COMBINED["id"]})
    if partial_combined and not route_ids:
        blockers.append({"code": "missing_r5_catalogue_option", "source": person["source"],
                         "requirement_id": COMBINED["id"]})
        return []
    route_choices = [(ids, elective) for ids in route_ids for elective in electives]
    if not partial_combined:
        for elective in electives:
            if len(elective) != 1 or elective[0][0]["required_months"] != 6:
                continue
            block, eligible, partial = elective[0]
            for key in COMBINED["credits"]:
                requirement = requirements[key]
                if requirement["expected_months"] or not requirement["remaining_months"]:
                    continue  # Keep a separately started core on its existing continuation route.
                qualifying = [option for option in eligible
                              if (credit := additional_r5_credit(option)) and credit["id"] == key]
                if qualifying:
                    route_choices.append((set(COMBINED["credits"]) - {key}, [(block, qualifying, partial)]))

    routes, failures = [], []
    for ids, elective in route_choices:
        route_person = {**person, "requirements": [r for r in person["requirements"]
                       if r["requirement_year"] != "R5" or r["requirement_id"] in ids | {"r5.elective"}]}
        errors = []
        route = prepare_blocks(route_person, options, planning_start, earlier_months, errors) + elective
        if errors:
            failures.extend(errors)
        elif sum(partial for _, _, partial in route) > 1:
            failures.append({"code": "conflicting_partial_r5_history", "source": person["source"]})
        else:
            routes.append(route)
    if not routes:
        blockers.extend(failures)
    return routes



def _add_route(model, person, route, start, resident_index, enabled=None):
    placements = add_blocks(model, person, route, start, resident_index, enabled)
    for key in COMBINED["credits"]:
        core = [p["start"] * p["variable"] for p in placements if p["option"]["requirement_id"] == key]
        if core:
            for p in placements:
                credit = additional_r5_credit(p["option"])
                if credit and credit["id"] == key:
                    # A separate core can precede an overlap elective, but the
                    # elective would already fulfil a core scheduled after it.
                    model.add(sum(core) <= p["start"]).only_enforce_if(p["variable"])
    return placements


def add_routes(model, person, routes, start, resident_index):
    if len(routes) == 1:
        return _add_route(model, person, routes[0], start, resident_index)
    choices = [model.new_bool_var(f"r5_route_{resident_index}_{i}") for i in range(len(routes))]
    model.add_exactly_one(choices)
    return [placement for i, (route, enabled) in enumerate(zip(routes, choices))
            for placement in _add_route(model, person, route, start, f"{resident_index}_route_{i}", enabled)]
