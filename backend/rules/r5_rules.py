"""R5 core routes and six-month or paired three-month elective blocks."""
import re
from collections import Counter
from itertools import product
from .r2_rules import add_blocks

if __package__ == "backend.rules":
    from ..workbook_import import month_number
    from ..programme_requirements import PROGRAMME_REQUIREMENTS, additional_r5_credit
else:
    from workbook_import import month_number
    from programme_requirements import PROGRAMME_REQUIREMENTS, additional_r5_credit


R5_ELECTIVE = PROGRAMME_REQUIREMENTS["R5"]["Elective"]["id"]
COMBINED = PROGRAMME_REQUIREMENTS["R5"]["Child and Geriatric Psychiatry"]
R5_CORES = COMBINED["credits"]
R5_TRAINING_MONTHS = 12


def r5_runs(months):
    """Group same-option training months across calendar years and LOA."""
    runs, active, previous = [], None, None
    for month in months:
        number = month_number(month["month"])
        if previous is not None and number != previous + 1:
            active = None
        previous = number
        if month["status"] == "loa":
            if active is not None:
                active["next_month"] = number + 1
            continue
        if month["status"] != "expected" or not month.get("requirement_id", "").startswith("r5."):
            active = None
            continue
        identity = (month["posting"], month["institution"])
        key = month["requirement_id"]
        if active is None or active["identity"] != identity or active["requirement_id"] != key:
            active = {"requirement_id": key, "identity": identity, "start": number, "count": 0,
                      "target": month.get("target") or {}, "start_month": month["month"]}
            runs.append(active)
        active["count"] += 1
        active["end_month"] = month["month"]
        active["next_month"] = number + 1
    return runs


def r5_credit_progress(runs):
    """Count credited components exactly once, retaining incomplete six-month blocks."""
    counts = Counter()
    for run in runs:
        key, length = run["requirement_id"], run["count"]
        credit = additional_r5_credit(run["target"])
        if key == COMBINED["id"]:
            counts[key] = max(counts[key], min(length, 6))
            if length == 6:
                for core in R5_CORES:
                    counts[core] += 3
        elif credit:
            if length == 6:
                counts[credit["id"]] += credit["months"]
                counts[R5_ELECTIVE] += 6 - credit["months"]
        else:
            counts[key] += length
    return counts


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
    counts = r5_credit_progress(runs)
    core_runs = Counter(run["requirement_id"] for run in runs)
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
                core_lengths.append((3, 6) if counts[core] > 3 or (core, 6) in requested else (3,))
        for lengths in product(*core_lengths):
            electives = R5_TRAINING_MONTHS - sum(lengths) - 6 * len(mixed)
            if electives not in (0, 3, 6):
                continue
            cores = []
            for key, length in zip(R5_CORES, lengths):
                if length == 6 and core_runs[key] > 1:
                    cores.extend([(key, 3, None)] * 2)
                elif length:
                    cores.append((key, length, None))
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


def _manual_core_templates(splits=((3, 9), (6, 6), (9, 3))):
    # A core can be completed as a three- or six-month block. Separate blocks
    # remain distinct even when they count towards the same requirement.
    partitions = {0: [()], 3: [(3,)], 6: [(6,), (3, 3)],
                  9: [(6, 3), (3, 6), (3, 3, 3)]}
    for child, geriatric in splits:
        for combined in ([], [(COMBINED["id"], 6, None)]):
            shared = 3 if combined else 0
            for lengths in product(partitions[child - shared], partitions[geriatric - shared]):
                yield combined + [(key, length, None) for key, blocks in zip(R5_CORES, lengths) for length in blocks]


def _fit_history(template, runs, options, resume_month):
    """Match each physical run to consecutive whole blocks and at most one open block."""
    matched = {}
    for run in runs:
        key, left = run["requirement_id"], run["count"]
        credit = _credit_key(run["target"])
        durations = {3, 6}
        if key == R5_ELECTIVE:
            offering = next((o for o in options if o["requirement_id"] == key
                             and (o["posting"], o["institution"]) == run["identity"]), run["target"])
            if offering.get("label"):
                durations = elective_durations(offering)
        for index, (req, duration, extra) in enumerate(template):
            if req != key or extra != credit or index in matched:
                continue
            if key == R5_ELECTIVE and duration not in durations:
                return None
            # Four/five adjacent months of a flexible elective already form one
            # six-month block. A three-only offering instead starts a second block.
            if key == R5_ELECTIVE and duration == 3 and 3 < left < 6 and 6 in durations:
                return None
            count = min(left, duration)
            if count < duration and (run is not runs[-1] or run["next_month"] != resume_month):
                return None
            matched[index] = {**run, "count": count}
            left -= count
            if not left:
                break
        if left:
            return None
    return matched


def _fitted_plans(runs, options, resume_month, requests=(), allow_split=False, manual_edit=False):
    # Preserve completed legacy elective credit (four months plus two). Core
    # history must still fit its own blocks even when all twelve months are present.
    electives = [r for r in runs if r["requirement_id"] == R5_ELECTIVE and not _credit_key(r["target"])]
    if sorted(r["count"] for r in electives) == [2, 4] and sum(r["count"] for r in runs) == 12:
        runs = [r for r in runs if r not in electives] + [{**electives[0], "count": 6}]

    regular = set()
    for template in _templates(runs, options, requests, allow_split):
        matched = _fit_history(template, runs, options, resume_month)
        if matched is not None:
            regular.add(tuple(template))
            yield template, matched, False
    if (regular and not manual_edit) or any(r["requirement_id"] == R5_ELECTIVE for r in runs):
        return

    # Only an edit may start an all-core plan. Recorded blocks that no ordinary
    # plan can finish may continue one. Prefer 6+6 while both splits still fit.
    for splits in (((6, 6),), ((3, 9), (9, 3))):
        found = False
        for template in _manual_core_templates(splits):
            if tuple(template) in regular:
                continue
            matched = _fit_history(template, runs, options, resume_month)
            if matched is not None:
                found = True
                yield template, matched, manual_edit
        if found and not manual_edit:
            return


def history_targets(runs, resume_month):
    """Use the least extended supported plan consistent with the recorded blocks."""
    def components(template):
        totals = Counter()
        for key, duration, credit in template:
            if key == COMBINED["id"]:
                totals.update({core: 3 for core in R5_CORES})
            elif credit:
                totals[credit] += 3
                totals[R5_ELECTIVE] += duration - 3
            else:
                totals[key] += duration
        totals.setdefault(R5_ELECTIVE, 0)
        return totals

    plans = (components(template) for template, _, _ in _fitted_plans(runs, (), resume_month))
    return min(plans, key=lambda t: sum(t[core] for core in R5_CORES), default=None)


def prepare_routes(person, options, planning_start, earlier_months, blockers, allow_split=False, requests=(), *, fixed=None):
    requirements = {r["requirement_id"]: r for r in person["requirements"]}
    runs = r5_runs(person["months"])
    routes, missing = [], None
    fixed_blocks = Counter()
    if fixed is not None:
        fixed_blocks = Counter((month["block_start"], month["target"]["requirement_id"])
                               for month in fixed["months"] if month["status"] == "posting"
                               and month["target"]["residency_year"] == "R5")
    manual_edit = bool(fixed_blocks) and all(key != R5_ELECTIVE for _, key in fixed_blocks)
    resume_month = None if earlier_months else month_number(planning_start)
    for template, matched, manual in _fitted_plans(runs, options, resume_month, requests, allow_split, manual_edit):
        if manual:
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
            if not route:
                return [[]]
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
