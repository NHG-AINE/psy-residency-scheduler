"""R5 core routes and six-month or paired three-month elective blocks."""
import re
from collections import Counter
from itertools import product
from .r2_rules import add_blocks

if __package__ == "backend.rules":
    from ..requirement_ledger import month_number, r5_runs, r5_credit_progress, R5_CORES, R5_ELECTIVE, R5_COMBINED, R5_TRAINING_MONTHS
    from ..programme_requirements import additional_r5_credit
else:
    from requirement_ledger import month_number, r5_runs, r5_credit_progress, R5_CORES, R5_ELECTIVE, R5_COMBINED, R5_TRAINING_MONTHS
    from programme_requirements import additional_r5_credit


COMBINED = R5_COMBINED


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



def _credit_key(option):
    credit = additional_r5_credit(option)
    return credit["id"] if credit else None



def balance_components(option):
    key = option["requirement_id"]
    if key == COMBINED["id"]:
        return R5_CORES
    credit = _credit_key(option)
    return (key, credit) if credit else (key,)


def _requested_components(requests, options):
    lengths, mixed = set(), set()
    by_key = {(o["requirement_id"], o["institution"], o["label"]): o for o in options}
    for row in requests:
        if row["status"] != "evaluable" or not row["fresh_duration"]:
            continue
        key, duration = row["requirement_id"], row["duration"]
        lengths.update((key, d) for d in row.get("requested_durations", [duration]))
        if key == R5_ELECTIVE and duration == 6:
            mixed.update(credit for option_key in row["option_keys"]
                         if (credit := _credit_key(by_key.get(option_key, {}))))
    return lengths, mixed


def _templates(runs, options, requests, allow_split):
    requested, mixed_requests = _requested_components(requests, options)
    _, history_long, _ = r5_credit_progress(runs)
    historical_cores = {run["requirement_id"] for run in runs}
    historical_mixed = {credit for run in runs if (credit := _credit_key(run["target"]))}
    available_mixed = {credit for option in options if (credit := _credit_key(option))}
    mixed_sets = [()] + [(core,) for core in R5_CORES if core in available_mixed | historical_mixed]
    if set(R5_CORES) <= mixed_requests | historical_mixed:
        mixed_sets.append(R5_CORES)
    # Each component sum is twelve. Mixed postings take one three-month core
    # component and three elective months. Combined core takes both core components.
    for mixed in mixed_sets:
        core_lengths = []
        for core in R5_CORES:
            if core in mixed:
                duplicate = (core in historical_mixed and (core in historical_cores or COMBINED["id"] in historical_cores)
                             or core in mixed_requests and ((core, 3) in requested or (COMBINED["id"], 6) in requested))
                core_lengths.append((0, 3) if duplicate else (0,))
            else:
                core_lengths.append((3, 6) if core in history_long or (core, 6) in requested else (3,))
        for lengths in product(*core_lengths):
            electives = R5_TRAINING_MONTHS - sum(lengths) - 6 * len(mixed)
            if electives not in (0, 3, 6):
                continue
            cores = [(key, length, None) for key, length in zip(R5_CORES, lengths) if length]
            elective_slots = [(R5_ELECTIVE, 6, core) for core in mixed]
            variants = [[]] if not electives else [[(R5_ELECTIVE, electives, None)]]
            if electives == 6 and (allow_split or any(run["requirement_id"] == R5_ELECTIVE and not _credit_key(run["target"])
                                                      for run in runs)):
                variants.append([(R5_ELECTIVE, 3, None)] * 2)
            for variant in variants:
                if all(not length or key not in mixed or key in historical_cores or (key, 3) in requested
                       for key, length in zip(R5_CORES, lengths)):
                    yield cores + elective_slots + variant
                if lengths == (3, 3) and (not mixed or COMBINED["id"] in historical_cores
                                          or (COMBINED["id"], 6) in requested):
                    yield [(COMBINED["id"], 6, None)] + elective_slots + variant


def _manual_core_templates():
    # A core can be completed as a three- or six-month block. Separate blocks
    # remain distinct even when they count towards the same requirement.
    partitions = {0: [()], 3: [(3,)], 6: [(6,), (3, 3)],
                  9: [(6, 3), (3, 6), (3, 3, 3)]}
    for child, geriatric in ((3, 9), (6, 6), (9, 3)):
        for combined in ([], [(COMBINED["id"], 6, None)]):
            shared = 3 if combined else 0
            for lengths in product(partitions[child - shared], partitions[geriatric - shared]):
                yield combined + [(key, length, None) for key, blocks in zip(R5_CORES, lengths) for length in blocks]


def _continues(run, months, planning_start, earlier_months):
    if earlier_months:
        return False
    next_month = month_number(run["end_month"]) + 1
    for month in months:
        number = month_number(month["month"])
        if number < next_month:
            continue
        if number != next_month or month["status"] != "loa":
            return False
        next_month += 1
    return next_month == month_number(planning_start)


def _fit_history(template, runs, options, months, planning_start, earlier_months):
    """Allocate recognised runs to the finite block pattern, pausing for LOA."""
    matched = {}
    for run in runs:
        key, length = run["requirement_id"], run["count"]
        credit = _credit_key(run["target"])
        available = [i for i, (req, _, extra) in enumerate(template)
                     if req == key and extra == credit and i not in matched]
        if not available:
            # A completed historical core may be credited as two separate
            # three-month runs. Only an unfinished block needs one exact site.
            index = next((i for i, (req, duration, _) in enumerate(template)
                          if req == key and duration == 6 and key in R5_CORES
                          and matched.get(i, {}).get("count") == 3 and length == 3), None)
            if index is not None:
                matched[index] = {**run, "count": 6}
                continue
            return None
        index = available[0]
        required = template[index][1]
        if length > required:
            # Consecutive same-site three-month electives may look like one run.
            three_only = key == R5_ELECTIVE and not credit and any(
                (o["posting"], o["institution"]) == run["identity"] and elective_durations(o) == (3,)
                for o in options if o["requirement_id"] == R5_ELECTIVE)
            if (key == R5_ELECTIVE and not credit and required == 3 and len(available) > 1
                    and (length == 6 or 3 < length < 6 and three_only)):
                matched[index] = {**run, "count": 3}
                index, length = available[1], length - 3
                required = template[index][1]
            else:
                return None
        if length < required and not _continues(run, months, planning_start, earlier_months):
            other_completed = key in R5_CORES and length == 3 and required == 6 and sum(
                other["requirement_id"] == key and other["count"] == 3 for other in runs) == 2
            if not other_completed:
                return None
        matched[index] = {**run, "count": length}
    return matched


def prepare_routes(person, options, planning_start, earlier_months, blockers, allow_split=False, requests=(), *, fixed=None):
    requirements = {r["requirement_id"]: r for r in person["requirements"]}
    runs = r5_runs(person["months"])
    _, _, pending = r5_credit_progress(runs)
    if not pending and all(not requirements[key]["remaining_months"] for key in (*R5_CORES, R5_ELECTIVE)):
        return [[]]

    routes, missing = [], None
    templates = _templates(runs, options, requests, allow_split)
    fixed_blocks, manual = Counter(), set()
    if fixed is not None:
        fixed_blocks = Counter((month["block_start"], month["target"]["requirement_id"])
                               for month in fixed["months"] if month["status"] == "posting"
                               and month["target"]["residency_year"] == "R5")
    if fixed_blocks and all(key != R5_ELECTIVE for _, key in fixed_blocks):
        generated = list(templates)
        manual = {tuple(template) for template in _manual_core_templates()} - {tuple(template) for template in generated}
        templates = [*generated, *sorted(manual)]
    for template in templates:
        matched = _fit_history(template, runs, options, person["months"], planning_start, earlier_months)
        if matched is None:
            continue
        if manual and tuple(template) in manual:
            remaining = Counter((key, duration - matched.get(index, {}).get("count", 0))
                                for index, (key, duration, _) in enumerate(template))
            last, last_length = next(reversed(fixed_blocks.items()))
            # Only the final visible block can continue beyond the horizon.
            blocks = Counter((key, count) for (_, key), count in list(fixed_blocks.items())[:-1])
            if blocks - remaining or not any(key == last[1] and length >= last_length for key, length in (remaining - blocks)):
                continue
        route = []
        for index, (key, duration, credit) in enumerate(template):
            run = matched.get(index)
            credited = run["count"] if run else 0
            if credited == duration:
                continue
            eligible = [o for o in options if o["requirement_id"] == key and _credit_key(o) == credit
                        and (key != R5_ELECTIVE or duration in elective_durations(o))
                        and (run is None or (o["posting"], o["institution"]) == run["identity"])]
            if not eligible:
                missing = key
                break
            block = {**requirements[key], "block_id": f"r5.block.{index}", "required_months": duration,
                     "expected_months": credited, "remaining_months": duration - credited}
            route.append((block, eligible, bool(credited)))
        else:
            if sum(partial for _, _, partial in route) <= 1:
                routes.append(route)
    if not routes:
        issue = {"code": "missing_r5_catalogue_option" if missing else "conflicting_partial_r5_history", "source": person["source"]}
        if missing:
            issue["requirement_id"] = missing
        blockers.append(issue)
    return routes


def add_routes(model, person, routes, start, resident_index):
    if len(routes) == 1:
        return add_blocks(model, person, routes[0], start, resident_index)
    choices = [model.new_bool_var(f"r5_route_{resident_index}_{i}") for i in range(len(routes))]
    model.add_exactly_one(choices)
    return [placement for i, (route, enabled) in enumerate(zip(routes, choices))
            for placement in add_blocks(model, person, route, start, f"{resident_index}_route_{i}", enabled)]
