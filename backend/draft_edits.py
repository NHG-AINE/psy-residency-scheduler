"""Validate whole-block changes against the same model used to generate drafts."""
from copy import deepcopy
from datetime import date
from collections import Counter
from itertools import groupby

if __package__:
    from .cluster_coverage import CLUSTERS
    from .rules import r1_rules, r4_rules, r5_rules
    from .requirement_ledger import R5_CORES, R5_TRAINING_MONTHS, r5_credit_progress, r5_runs
    from .scheduler_inputs import prepare_scheduler_inputs
    from .scheduler import draft_schedule, draft_source_key
    from .workbook_import import recorded_years
else:
    from cluster_coverage import CLUSTERS
    from rules import r1_rules, r4_rules, r5_rules
    from requirement_ledger import R5_CORES, R5_TRAINING_MONTHS, r5_credit_progress, r5_runs
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


def _month_targets(person):
    return [m["target"]["source"] if m.get("target") else None for m in person["months"]]


class DraftWarningBaselineRequired(ValueError):
    pass


def _warning_diagnostics(draft):
    return {key: draft[key] for key in ("preference_scores", "capacity_overflows", "singletons", "soft_results")}


def _has_warning_diagnostics(draft, scores, months):
    try:
        soft = draft["soft_results"]
        ratios = soft["monthly_ratios"]
        return (scores <= draft["preference_scores"].keys()
                and set(r1_rules.ROUTES) <= soft["route_counts"].keys()
                and {(row["month"], row["route"]) for row in ratios}
                == {(month, route) for month in months for route in r1_rules.PAIRED_ROUTES}
                and all("deviation" in row for row in ratios)
                and isinstance(soft["site_allocations"], list)
                and all({"requirement_id", "posting"} <= row.keys() and row["targets"].keys() <= row["counts"].keys()
                        for row in soft["site_allocations"])
                and isinstance(draft["capacity_overflows"], list)
                and all({"month", "requirement_id", "institution", "label", "assigned"} <= row.keys()
                        for row in draft["capacity_overflows"])
                and isinstance(draft["singletons"], list)
                and all({"month", "requirement_id", "institution", "label", "resident_source"} <= row.keys()
                        for row in draft["singletons"]))
    except (AttributeError, KeyError, TypeError):
        return False


def _recover_warning_diagnostics(workbook, store, prepared, residents, reason):
    try:
        fixed = {draft_source_key(person["source"]): person for person in residents}
        if len(fixed) != len(residents):
            raise ValueError(reason)
        recovered = draft_schedule(workbook, store, max_seconds=10, fixed=fixed, prepared=prepared)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(reason) from exc
    if recovered["status"] != "feasible":
        raise ValueError(reason)
    return _warning_diagnostics(recovered)


def _matches_original_baseline(baseline, residents):
    try:
        return {draft_source_key(row["source"]): (row["route"], row["months"]) for row in baseline["residents"]} == {
            draft_source_key(row["source"]): (row["route"], _month_targets(row)) for row in residents
        }
    except (KeyError, TypeError):
        return False


def _check_warning_sources(prepared, residents, people):
    offerings = {draft_source_key(option["source"]) for option in prepared["catalogue_options"] if option["valid"]}
    for person in residents:
        for month in person["months"]:
            target = month.get("target") or {}
            source = target.get("source")
            if month["status"] == "posting" and (not isinstance(source, dict) or draft_source_key(source) not in offerings):
                name = people[draft_source_key(person["source"])].get("name") or "this resident"
                raise ValueError(f"Warnings could not be recovered for {name} in {_month(month['month'])}. "
                                 "The saved posting could not be matched to the workbook’s Postings tab.")


def _comparison(draft):
    # Only keep the information needed to clear resolved warnings after subsequent edits.
    return {**_warning_diagnostics(draft),
            "residents": [{
                "source": person["source"], "route": person["route"], "cluster_coverage": person["cluster_coverage"],
                "months": _month_targets(person),
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
    previous_ratios = {(row["month"], row["route"]): row["deviation"] for row in previous["monthly_ratios"]}
    for row in current["monthly_ratios"]:
        if row["deviation"] > previous_ratios[(row["month"], row["route"])]:
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
    future = original["carryforward"]
    last = next(m for m in reversed(original["months"]) if m["status"] == "posting")
    previous = last["target"]
    for block in moved:
        target = block[0]["target"]
        if (any(m["month"] == last["month"] for m in block)
                and target["requirement_id"] == previous["requirement_id"]
                and target["source"] != previous["source"]):
            for item in future:
                if (item["requirement_id"], item["institution"], item.get("label", previous["label"])) == (
                        previous["requirement_id"], previous["institution"], previous["label"]):
                    return f"Continue {previous['label']} at the same institution. The draft has {_amount(item['months'], 'training month')} planned there next year."
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
        projected = []
        for month in person["months"]:
            option = options.get(draft_source_key(month["target"]["source"])) if month["status"] == "posting" else None
            projected.append({**option, "month": month["month"], "status": "expected", "target": option} if option else month)
        runs = r5_runs(progress["months"] + projected)
        if sum(run["count"] for run in runs) == R5_TRAINING_MONTHS:
            credits, _, _ = r5_credit_progress(runs)
            missing = [f"{_amount(3 - credits[key], 'month')} of R5 {requirements[key]['posting']}"
                       for key in R5_CORES if credits[key] < 3]
            if missing:
                name = person["name"] or "This resident"
                return f"{name} would still need {' and '.join(missing)}."
    if future:
        return "This placement cannot fit with the other blocks and future assignments in place. Check the resident’s remaining requirements and postings planned beyond this year."
    if "R5" in years:
        return "These dates leave no valid R5 plan with the other blocks in place. Check the remaining Child, Geriatric and elective months, including any credit earned by a six-month block."
    return "This placement cannot fit the resident’s remaining training with the other blocks in place. Check their posting history, block length and training order."


def validate_draft_change(workbook, store, draft, change, baseline_residents=None):
    if draft.get("status") not in {"feasible", "optimal", "edited"} or draft["cutoff"] != f"{workbook['target_year']}-06":
        raise ValueError("Generate a draft for this planning year before editing postings.")
    if not draft.get("edit_options"):
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
    warning_scores = {"posting_balance", *r1_rules.SOFT_PRIORITIES, *draft.get("soft_priority", [])}
    warning_months = [month["month"] for month in prepared["planning_months"]]
    baseline = draft.get("edit_baseline")
    recover_current = not _has_warning_diagnostics(draft, warning_scores, warning_months)
    recover_baseline = baseline is not None and not _has_warning_diagnostics(baseline, warning_scores, warning_months)
    if recover_baseline and baseline_residents is None:
        raise DraftWarningBaselineRequired("The original placements are needed to recover this draft’s warning data. Reopen it with its Undo history.")
    if recover_baseline and not _matches_original_baseline(baseline, baseline_residents):
        raise ValueError("The original placements do not match the saved draft’s warning baseline.")
    if recover_current:
        _check_warning_sources(prepared, draft["residents"], fixed)
    if recover_baseline:
        _check_warning_sources(prepared, baseline_residents, fixed)
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

    result = draft_schedule(workbook, store, max_seconds=10, fixed=fixed, prepared=prepared)
    if result["status"] == "infeasible":
        return blocked("hard_constraint", _explain_conflict(prepared, person, original, moved))
    if result["status"] != "feasible":
        raise ValueError("The change could not be validated. Check the workbook and try again.")
    if recover_current:
        reason = "Warnings could not be recovered from this draft’s saved placements. Generate a new draft to make changes."
        draft = {**draft, **_recover_warning_diagnostics(workbook, store, prepared, draft["residents"], reason)}
    if recover_baseline:
        reason = "Warnings could not be recovered from this draft’s original placements. Generate a new draft to make changes."
        baseline = {**baseline, **_recover_warning_diagnostics(workbook, store, prepared, baseline_residents, reason)}
    comparison = _comparison(draft)
    issues = _soft_issues(comparison, result)
    if baseline is None:
        baseline = comparison
    edit_warnings = issues if baseline is comparison else _soft_issues(baseline, result)
    # Restoring the generated placements can bring back preferences the original draft missed.
    if issues and not edit_warnings and [
        (p["source"], p["months"]) for p in baseline["residents"]
    ] == [(p["source"], _month_targets(p)) for p in result["residents"]]:
        issues = []
    result.update(status="edited", edit_baseline=baseline, edit_warnings=edit_warnings)
    result.pop("optimisation_stages", None)
    return {"draft": result, "issues": issues}
