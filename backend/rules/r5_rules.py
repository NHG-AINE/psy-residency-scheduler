"""R5 requirements and the supported six-month elective scope."""
from .r2_rules import partial_posting_identity, add_blocks

if __package__ == "backend.rules":
    from ..requirement_ledger import month_number
    from ..programme_requirements import PROGRAMME_REQUIREMENTS
else:
    from requirement_ledger import month_number
    from programme_requirements import PROGRAMME_REQUIREMENTS


COMBINED = PROGRAMME_REQUIREMENTS["R5"]["Child and Geriatric Psychiatry"]


def supported_option(option):
    remarks = option["remarks"] or []
    if not remarks:
        return True
    return option["category"] == "elective" and all(
        r["text"].strip().casefold() == "(all required 6 months duration)" for r in remarks)


def prepare_blocks(person, options, planning_start, earlier_months, blockers):
    blocks = []
    for requirement in person["requirements"]:
        if requirement["requirement_year"] != "R5" or not requirement["remaining_months"]:
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

def prepare_routes(person, options, planning_start, earlier_months, blockers):
    """Choose separate cores or one combined core, plus the six-month elective."""
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
    routes, failures = [], []
    for ids in route_ids:
        route_person = {**person, "requirements": [r for r in person["requirements"]
                       if r["requirement_year"] != "R5" or r["requirement_id"] in ids | {"r5.elective"}]}
        errors = []
        route = prepare_blocks(route_person, options, planning_start, earlier_months, errors)
        if errors:
            failures.extend(errors)
        else:
            routes.append(route)
    if not routes:
        blockers.extend(failures)
    return routes


def add_routes(model, person, routes, start, resident_index):
    if len(routes) == 1:
        return add_blocks(model, person, routes[0], start, resident_index)
    choices = [model.new_bool_var(f"r5_route_{resident_index}_{i}") for i in range(len(routes))]
    model.add_exactly_one(choices)
    return [placement for i, (route, enabled) in enumerate(zip(routes, choices))
            for placement in add_blocks(model, person, route, start, f"{resident_index}_route_{i}", enabled)]
