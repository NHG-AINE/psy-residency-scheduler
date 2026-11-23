"""Validate whole-block changes against the same model used to generate drafts."""
from copy import deepcopy
from datetime import date
from collections import Counter
from itertools import groupby

if __package__:
    from .cluster_coverage import CLUSTERS
    from .rules import r1_rules, r4_rules, r5_rules
    from .scheduler_inputs import prepare_scheduler_inputs
    from .scheduler import draft_schedule, draft_source_key
    from .workbook_import import recorded_years
else:
    from cluster_coverage import CLUSTERS
    from rules import r1_rules, r4_rules, r5_rules
    from scheduler_inputs import prepare_scheduler_inputs
    from scheduler import draft_schedule, draft_source_key
    from workbook_import import recorded_years


def _month(value):
    return date.fromisoformat(value + "-01").strftime("%B")


def _amount(n, noun):
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _capacity_key(row):
    return row["month"], row["requirement_id"], row["institution"], row["label"]


def _periods(rows, identity):
    """Coalesce adjacent months only when the warning applies to the same people."""
    for _, group in groupby(sorted(rows, key=lambda r: (identity(r), r["month"])), identity):
        last = None
        run = []
        for row in group:
            year, month = map(int, row["month"].split("-"))
            index = year * 12 + month
            if run and index != last + 1:
                yield run
                run = []
            run.append(row)
            last = index
        if run:
            yield run


def _period(run):
    first = _month(run[0]["month"])
    return first if len(run) == 1 else f"{first} to {_month(run[-1]['month'])}"


def _comparison(draft):
    # Only keep the information needed to clear resolved warnings after subsequent edits.
    return {**{key: draft[key] for key in ("preference_scores", "capacity_overflows", "singletons", "soft_results")},
            "residents": [{
                "source": person["source"], "route": person["route"], "cluster_coverage": person["cluster_coverage"],
                "months": [m["target"]["source"] if m.get("target") else None for m in person["months"]],
                "requests": [r["status"] for r in person["requests"]]
            } for person in draft["residents"]]}


def _soft_issues(before, after):
    old_capacity = {_capacity_key(row): row["assigned"] for row in before.get("capacity_overflows", [])}
    issues = []
    def warn(code, affected, message):
        if affected:
            issues.append({"severity": "soft", "code": code, "affected": affected, "message": message})

    increased = [r for r in after["capacity_overflows"] if r["assigned"] > old_capacity.get(_capacity_key(r), r["max"])]
    def same_overflow(row):
        occupants = tuple(str(draft_source_key(p["source"])) for p in row["residents"])
        return _capacity_key(row)[1:], row["assigned"], row["max"], occupants

    for run in _periods(increased, same_overflow):
        row = run[0]
        institution = row["institution"]
        posting = row["label"].removeprefix(institution + " ")
        affected = [{"source": resident["source"], "month": part["month"]} for part in run for resident in part["residents"]]
        warn("capacity_overflow", affected, f"{_period(run)} at {institution} would have {_amount(row['assigned'], 'resident')} in {posting}. The max is {row['max']}.")
    def worsened(key):
        return after["preference_scores"].get(key, 0) > before["preference_scores"].get(key, 0)
    old_people = {draft_source_key(p["source"]): p for p in before["residents"]}
    changed = []
    for person in after["residents"]:
        old = old_people[draft_source_key(person["source"])]
        changes = [m for old_source, m in zip(old["months"], person["months"])
                   if m.get("target") and old_source != m["target"]["source"]]
        anchors = [{"month": m["month"], "source": person["source"]} for m in changes]
        changed.extend(anchors)
        if not anchors:
            continue
        for status, request in zip(old["requests"], person["requests"]):
            if status == "met" and request["status"] == "not_met" and "duplicate_of" not in request:
                names = [r["request"]["posting_request"] for r in request.get("alternatives", [request])]
                warn("resident_requests", anchors, f"The request for {' or '.join(filter(None, names))} would no longer be met.")
        coverage = person["cluster_coverage"]["projected"]["visited"]
        for cluster in old["cluster_coverage"]["projected"]["visited"]:
            if cluster not in coverage:
                warn("missing_clusters", anchors, f"This would remove the resident’s planned {cluster} exposure. They still need all three clusters by the end of R4.")
        if worsened("inpatient_destination"):
            sites = r1_rules.PREFERRED_INPATIENT_CLUSTERS.get(person["route"], ())
            for m in changes:
                t = m["target"]
                if t["requirement_id"] == "r1.inpatient_psychiatry" and sites and not any(t["institution"] in CLUSTERS[s] for s in sites):
                    warn("inpatient_destination", anchors, f"After the {person['route']} route, {' or '.join(sites)} is preferred for inpatient training. This block is at {t['institution']}.")
                    break
        if worsened("posting_balance"):
            for m in changes:
                t = m["target"]
                if t["residency_year"] in {"R2", "R4", "R5"}:
                    count = sum(n["month"] == m["month"] and n["target"]["requirement_id"] == t["requirement_id"]
                                for p in after["residents"] for n in p["months"] if n.get("target"))
                    posting = t["label"].removeprefix(t["institution"] + " ")
                    requirement = "electives" if t["category"] == "elective" else posting
                    warn("posting_balance", anchors, f"The monthly spread would be less even. In {_month(m['month'])}, {_amount(count, 'resident')} would be assigned to {t['residency_year']} {requirement}.")
                    break
    if worsened("inpatient_allocation"):
        old_groups = {(group["requirement_id"], group["posting"]): group for group in before["soft_results"]["site_allocations"]}
        for group in after["soft_results"]["site_allocations"]:
            old = old_groups.get((group["requirement_id"], group["posting"]))
            if not old or old == group:
                continue
            counts, targets = group["counts"], group["targets"]
            for site, n in counts.items():
                if site in targets:
                    if abs(n - targets[site]) <= abs(old["counts"].get(site, 0) - old["targets"].get(site, 0)):
                        continue
                    message = f"{site} would have {_amount(n, 'resident')} in {group['posting']}. The target is {targets[site]}."
                else:
                    if max(counts.values()) - min(counts.values()) <= max(old["counts"].values()) - min(old["counts"].values()):
                        continue
                    high, low = max(counts, key=counts.get), min(counts, key=counts.get)
                    message = f"{group['posting']} would have {_amount(counts[high], 'resident')} at {high} and {counts[low]} at {low}. The programme aims for an even spread."
                warn("inpatient_allocation", changed, message)
                break
    for key in ("r3_missing_clusters", "missing_clusters"):
        if worsened(key) and not any(i["code"] == "missing_clusters" for i in issues):
            warn(key, changed, "The resident would have fewer opportunities to train in a new cluster during R3." if key.startswith("r3") else "The resident would have fewer opportunities to train in a new cluster during R1 and R2.")
    previous = before["soft_results"]
    current = after["soft_results"]
    for route, n in current["route_counts"].items():
        target = after["soft_targets"]["routes"][route]
        if abs(n - target) > abs(previous["route_counts"][route] - target):
            warn("incoming_route_distribution", changed, f"The {route} route would have {_amount(n, 'resident')}. The target for this intake is {target}.")
    for old, row in zip(previous["monthly_ratios"], current["monthly_ratios"]):
        if row["deviation"] > old["deviation"]:
            anchors = [a for a in changed if a["month"] == row["month"]]
            warn("monthly_medicine_neurology_ratio", anchors, f"In {_month(row['month'])}, the {row['route']} route would have {row['medicine']} in Medicine and {row['neurology']} in Neurology. The usual split is 2 to 1.")
    def peer_key(row):
        return (_capacity_key(row), draft_source_key(row["resident_source"]))
    old_peers = {peer_key(row) for row in before["singletons"]}
    people = {draft_source_key(p["source"]): p for p in after["residents"]}
    new_peers = [r for r in after["singletons"] if peer_key(r) not in old_peers]
    for run in _periods(new_peers, lambda r: (_capacity_key(r)[1:], str(draft_source_key(r["resident_source"])))):
        row = run[0]
        source = row["resident_source"]
        name = people[draft_source_key(source)]["name"] or "This resident"
        when = ("in " if len(run) == 1 else "from ") + _period(run)
        warn("singleton_months", [{"month": part["month"], "source": source} for part in run],
             f"{name} would be the only resident in {row['label']} {when}.")
    order = after["soft_priority"]
    issues.sort(key=lambda issue: order.index(issue["code"]) if issue["code"] in order else len(order))
    return issues


def _explain_conflict(prepared, person, original, moved):
    """Describe evidence for a rejected placement. Only the scheduler decides feasibility."""
    progress = next(p for p in prepared["residents"] if draft_source_key(p["source"]) == draft_source_key(person["source"]))
    options = {draft_source_key(o["source"]): o for o in prepared["catalogue_options"]}
    requirements = {r["requirement_id"]: r for r in progress["requirements"]}
    planned = [m["target"] for m in person["months"] if m["status"] == "posting"]
    history = [m for m in progress["months"] if m["status"] == "expected"]
    for block in moved:
        target = block[0]["target"]
        option = options[draft_source_key(target["source"])]
        key = option["requirement_id"]
        if key == "r4.inpatient_psychiatry" and option["institution"] == "IMH":
            imh = sum(t["requirement_id"] == "r1.inpatient_psychiatry" and t["institution"] == "IMH" for t in planned)
            if r4_rules.completed_r1_inpatient_at_imh(progress, imh):
                return "Choose another institution for R4 Inpatient Psychiatry. This resident already has six months of R1 Inpatient Psychiatry at IMH in their history or draft."
        req = requirements[key]
        past = [m for m in history if m.get("requirement_id") == key]
        if option["residency_year"] in {"R2", "R3", "R4"} and req["remaining_months"] and past and all(m["institution"] != option["institution"] for m in past):
            return f"Continue {req['posting']} at {past[-1]['institution']}. This resident has completed {req['expected_months']} of {req['required_months']} months there."
        if option["residency_year"] == "R5" and option["category"] == "elective" and r5_rules.elective_durations(option) == (6,) and len(block) < 6 and block[-1]["month"] != person["months"][-1]["month"]:
            return f"{option['label']} needs six training months at the same institution. This block has {_amount(len(block), 'month')}."
    years = [target["residency_year"] for target in planned]
    if years != sorted(years):
        for i, year in enumerate(years):
            earlier = next((y for y in years[i + 1:] if y < year), None)
            if earlier:
                return f"Complete {earlier} before starting {year}. This change would leave {earlier} postings after the start of {year}."
    if any(t["requirement_id"].startswith("r1.") for t in (b[0]["target"] for b in moved)):
        evidence = [*history, *planned]
        gm = {t["institution"] for t in evidence if t.get("requirement_id") == "r1.general_medicine"}
        neuro = {t["institution"] for t in evidence if t.get("requirement_id") == "r1.neurology"}
        if ("TTSH" in gm and "SGH" in neuro) or ("SGH" in gm and "NNI" in neuro):
            return "Pair TTSH General Medicine with NNI Neurology, or keep both postings at SGH."
        return "The R1 plan needs Medicine and Neurology in the first six training months and Inpatient Psychiatry in the next six. Keep the paired institutions and permitted block lengths."
    for cluster in original["cluster_coverage"]["projected"]["visited"]:
        if cluster not in original["cluster_coverage"]["historical"]["visited"] and not any(t["institution"] in CLUSTERS[cluster] and t["residency_year"] != "R5" for t in planned):
            return f"This removes the resident’s only planned {cluster} posting. All three clusters are required by the end of R4."
    counts = Counter(t["requirement_id"] for t in planned)
    for block in moved:
        original_target = next(m["target"] for m in original["months"] if m["month"] == block[0]["month"])
        req = requirements[original_target["requirement_id"]]
        if req["requirement_year"] in {"R2", "R3", "R4"} and block[0]["target"]["requirement_id"] != req["requirement_id"] and counts[req["requirement_id"]] < req["remaining_months"]:
            missing = req["remaining_months"] - counts[req["requirement_id"]]
            return f"This would leave {_amount(missing, 'month')} of {req['requirement_year']} {req['posting']} unfinished."
    if "R5" in years:
        return "These dates leave no valid R5 plan with the other blocks in place. Check the remaining Child, Geriatric and elective months, including any credit earned by a six-month block."
    return "This placement cannot fit the resident’s remaining training with the other blocks in place. Check their posting history, block length and training order."


def validate_draft_change(workbook, store, draft, change):
    if draft.get("status") not in {"feasible", "optimal", "edited"} or draft["cutoff"] != f"{workbook['target_year']}-06":
        raise ValueError("Generate a draft for this planning year before editing postings.")
    if not draft.get("edit_options") or "preference_scores" not in draft:
        raise ValueError("Generate a new draft to edit its posting blocks.")
    fixed = {draft_source_key(person["source"]): person for person in deepcopy(draft["residents"])}
    if len(fixed) != len(draft["residents"]):
        raise ValueError("The draft contains duplicate resident rows. Generate a new draft.")
    source = draft_source_key(change["resident"])
    person = fixed.get(source)
    if person is None:
        raise ValueError("Choose a generated posting block in the draft.")
    original = next(p for p in draft["residents"] if draft_source_key(p["source"]) == source)
    start = change["start"]
    end = change.get("destination")

    def blocked(code, message):
        return {"draft": None, "issues": [{"severity": "hard", "code": code, "message": message,
                                          "affected": [{"source": person["source"], "month": month}
                                                       for month in (start, end) if month]}]}

    first = [m for m in person["months"] if m["status"] == "posting" and m.get("block_start") == start]
    if not first:
        return blocked("not_generated", "Only generated posting blocks can be changed.")
    moved = [first]
    kind = change["kind"]
    if kind in {"swap", "insert"}:
        second = [m for m in person["months"] if m["status"] == "posting" and m.get("block_start") == end]
        if any(m["month"] == end and m["status"] == "loa" for m in person["months"]):
            return blocked("leave", f"{_month(end)} is recorded as leave. Choose a block outside the leave period.")
        if not second or end == start:
            return blocked("invalid_destination", "Choose another generated posting block in the same resident’s row.")
        if kind == "swap":
            if len(first) != len(second):
                return blocked("unequal_length", f"Only equal-length blocks can swap. These blocks span {len(first)} and {len(second)} training months.")
            targets = [second[0]["target"], first[0]["target"]]
            moved.append(second)
        else:
            low = min(start, end)
            high = max(first[-1]["month"], second[-1]["month"])
            span = [m for m in person["months"] if low <= m["month"] <= high]
            if any(m["status"] not in {"posting", "loa"} for m in span):
                return blocked("outside_draft", "Choose a destination within the same generated training period.")
            training = [m for m in span if m["status"] == "posting"]
            order = [(key, list(months)) for key, months in groupby(training, key=lambda m: m["block_start"])]
            original_order = [key for key, _ in order]
            order = [item for item in order if item[0] != start]
            index = next(i for i, (key, _) in enumerate(order) if key == end)
            order.insert(index + (change["side"] == "after"), (start, first))
            if [key for key, _ in order] == original_order:
                return blocked("no_change", "Choose an insertion point that changes the block order.")
            # Pack the reordered blocks into the same training months, leaving LOA in place.
            blocks = [(block[0]["target"], len(block)) for _, block in order]
            moved = []
            offset = 0
            for option, length in blocks:
                block = training[offset:offset + length]
                for month in block:
                    month.update(label=option["label"], target=option, block_start=block[0]["month"])
                moved.append(block)
                offset += length
    prepared = prepare_scheduler_inputs(workbook, store)
    if kind == "edit":
        years = recorded_years(person["projected_year"]) | recorded_years(person["recorded_year"])
        options = [option for option in prepared["catalogue_options"] if option["valid"] and recorded_years(option["residency_year"]) & years
                   and option["posting"] == change["posting"] and option["institution"] == change["institution"]
                   and (not change.get("offering") or option["source"] == change["offering"])]
        if not options:
            return blocked("catalogue_offering", "Choose a posting and institution offered for this resident’s training years.")
        targets = options
        if len(options) > 1:
            return blocked("ambiguous_offering", "The workbook lists more than one matching offering for this posting and institution.")
    if kind != "insert":
        if all(draft_source_key(block[0]["target"]["source"]) == draft_source_key(option["source"]) for block, option in zip(moved, targets)):
            return blocked("no_change", "Choose a different posting or institution.")
        for block, option in zip(moved, targets):
            for month in block:
                month.update(label=option["label"], target=option)

    # Insertion changes timing only. Keep the edited resident's route and carryforward fixed too.
    result = draft_schedule(workbook, store, max_seconds=10, fixed=fixed,
                            edited_source=None if kind == "insert" else source, prepared=prepared)
    if result["status"] == "infeasible":
        return blocked("hard_constraint", _explain_conflict(prepared, person, original, moved))
    if result["status"] != "feasible":
        raise ValueError("The change could not be validated. Check the workbook and try again.")
    comparison = _comparison(draft)
    issues = _soft_issues(comparison, result)
    baseline = draft.get("edit_baseline", comparison)
    result.update(status="edited", edit_baseline=baseline,
                  edit_warnings=issues if baseline is comparison else _soft_issues(baseline, result))
    result.pop("optimisation_stages", None)
    return {"draft": result, "issues": issues}
