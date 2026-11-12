"""Expected programme progress from workbook evidence; never certified training credit."""
from collections import defaultdict
from datetime import date

if __package__:
    from .cluster_coverage import cluster_coverage
    from .history_review import evaluate_review, mcr_key
    from .programme_requirements import PROGRAMME_REQUIREMENTS, R1_COMPLETION_ROUTES, validate_posting
    from .workbook_import import intake_slot_id, normalized_label, recorded_years
else:
    from cluster_coverage import cluster_coverage
    from history_review import evaluate_review, mcr_key
    from programme_requirements import PROGRAMME_REQUIREMENTS, R1_COMPLETION_ROUTES, validate_posting
    from workbook_import import intake_slot_id, normalized_label, recorded_years


BLOCKED_IDENTITIES = {"missing_mcr", "missing_name", "duplicate_mcr", "conflicting_identity"}


def month_number(value):
    parsed = date.fromisoformat(value + "-01")
    return parsed.year * 12 + parsed.month - 1


def source_key(source):
    return tuple(source.get(key) for key in ("sheet", "row", "column"))


def build_requirement_ledger(workbook, store):
    """Build selected-roster expected progress before the planning period.

    Resolution remains global so saved exact periods are not broadened/truncated.
    Resolved current/earlier-year postings, including remediation, count duration.
    This does not certify training completion or rewrite review decisions.
    """
    try:
        start = workbook["months"][0]["month"]
        start_number = month_number(start)
        target_year = workbook.get("target_year")
        if target_year is not None and date.fromisoformat(start + "-01").year != target_year:
            raise ValueError("planning start does not agree with target_year")
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError("Valid planning months[0].month agreeing with target_year are required") from error
    cutoff_number = start_number - 1
    cutoff = f"{cutoff_number // 12:04d}-{cutoff_number % 12 + 1:02d}"
    blocked = {source_key(record.get("source", {}))[:2]
               for issue in workbook.get("issues", []) if issue.get("code") in BLOCKED_IDENTITIES
               for record in issue.get("records", [])}

    placeholder_blocked = blocked | {
        source_key(record.get("source", {}))[:2]
        for issue in workbook.get("issues", [])
        if issue.get("code") in {"duplicate_intake_placeholder", "unclear_intake", "excess_intake"}
        for record in issue.get("records", [])}

    def safe(resident):
        return bool(resident.get("source", {}).get("kind") != "intake_placeholder"
                    and mcr_key(resident.get("mcr")) and normalized_label(resident.get("name"))
                    and source_key(resident.get("source", {}))[:2] not in blocked
                    and ("annual_sheets" in workbook or resident.get("match_status") != "ambiguous"))

    resolved = defaultdict(list)
    for entry in evaluate_review(workbook, store)["entries"]:
        for month, source in zip(entry["months"], entry["sources"]):
            resolved[(mcr_key(entry["mcr"]), normalized_label(entry["name"]), month["month"], source_key(source))].append(entry)
    annual = workbook.get("annual_sheets", workbook.get("histories", []) + [{"residents": workbook.get("residents", [])}])
    roster_identities = {source_key(r["source"])[:2]:
                         (mcr_key(r.get("mcr")), normalized_label(r.get("name")))
                         for r in workbook.get("residents", [])}

    def linked_identity(resident):
        original = (mcr_key(resident.get("mcr")), normalized_label(resident.get("name")))
        target = resident.get("matched_resident_source")
        return roster_identities.get(source_key(target)[:2], original) if target else original

    raw = defaultdict(lambda: defaultdict(list))
    unsafe_history = set()
    for sheet in annual:
        for resident in sheet["residents"]:
            identity = linked_identity(resident)
            if not safe(resident):
                if any(month_number(posting["month"]) < start_number for posting in resident["postings"]):
                    unsafe_history.add(identity)
                continue
            for posting in resident["postings"]:
                month = posting["month"]
                if month_number(month) >= start_number:
                    continue
                evidence = {"value": posting.get("value"), "status": posting["status"],
                            "recorded_year": resident.get("residency_year"), "source": posting["source"],
                            "resident_source": resident["source"]}
                outcome = {"status": posting["status"], "reasons": []}
                if posting["status"] == "posting":
                    # Review decisions remain keyed to original source identity.
                    entries = resolved.get((mcr_key(resident.get("mcr")), normalized_label(resident.get("name")),
                                            month, source_key(posting["source"])), [])
                    outcomes = [_allocation(entry, workbook) for entry in entries]
                    outcome = outcomes[0] if outcomes and all(item == outcomes[0] for item in outcomes) else {
                        "status": "pending", "reasons": ["unresolved_history"]}
                raw[identity][month].append((evidence, outcome))
    residents = []
    for resident in workbook.get("residents", []):
        identity = (mcr_key(resident.get("mcr")), normalized_label(resident.get("name")))
        slot = intake_slot_id(resident, int(start[:4]))
        placeholder = bool(slot and resident.get("slot_id") == slot
                           and source_key(resident["source"])[:2] not in placeholder_blocked
                           and (resident["source"].get("kind") != "intake_placeholder"
                                or resident["source"].get("slot_id") == slot))
        identity_safe = safe(resident) or placeholder
        months = []
        for month, values in sorted(raw[identity].items()) if identity_safe and not placeholder else []:
            outcomes = [outcome for _, outcome in values]
            outcome = outcomes[0] if all(item == outcomes[0] for item in outcomes) else {
                "status": "pending", "reasons": ["conflicting_month_evidence"]}
            months.append({"month": month, **outcome, "evidence": [evidence for evidence, _ in values]})
        summaries = _summaries(months)
        by_id = {item["requirement_id"]: item for item in summaries}
        routes = [{"requirement_ids": list(route),
                   "evidence_status": "supported" if all(by_id[key]["evidence_status"] == "supported" for key in route)
                   else "partial" if any(by_id[key]["expected_months"] for key in route) else "not_evidenced"}
                  for route in R1_COMPLETION_ROUTES]
        residents.append({"name": resident.get("name"), "mcr": resident.get("mcr"),
                          "recorded_year": resident.get("residency_year"), "source": resident["source"], "slot_id": resident.get("slot_id"),
                          "identity_safe": identity_safe,
                          "warnings": (["unsafe_identity"] if not identity_safe else [])
                          + (["unsafe_historical_identity_evidence_excluded"] if not placeholder and identity in unsafe_history else []),
                          "months": months, "requirements": summaries, "r1_routes": routes,
                          "cluster_coverage": cluster_coverage(months),
                          "historical_notes": _historical_notes(resident, months)
                          if identity_safe and identity not in unsafe_history else []})
    return {"planning_start": start, "cutoff": cutoff, "basis": "projected_expected_not_certified", "residents": residents}



def _historical_notes(resident, months):
    """Describe proven timing exceptions only; never change credit or readiness."""
    intake = (resident.get("intake") or "").strip()
    if len(intake) != 4 or not intake.isdigit() or not 1 <= int(intake) <= 9999:
        return []
    expected_number = month_number(intake + "-07")
    counts, notes = defaultdict(int), []
    medicine, neurology, combined = (PROGRAMME_REQUIREMENTS["R1"][name] for name in
                                     ("General Medicine", "Neurology", "Medicine & Neurology"))
    previous = None
    for month in months:
        number = month_number(month["month"])
        if number != expected_number or month["status"] not in {"expected", "loa"}:
            break  # Missing or unresolved baseline evidence cannot prove an exception.
        expected_number += 1
        if month["status"] == "loa":
            previous = None
            continue
        completed_phase = (counts[medicine["id"]] >= medicine["months"] and counts[neurology["id"]] >= neurology["months"]
                           or counts[combined["id"]] >= combined["months"])
        if month["requirement_id"] == "r1.inpatient_psychiatry" and not completed_phase:
            label = month["target"]["label"]
            if previous is None or previous["posting"] != label:
                previous = {"code": "historical_r1_timing_exception", "posting": label,
                            "start": month["month"], "end": month["month"], "months": 0, "sources": []}
                notes.append(previous)
            previous["end"] = month["month"]
            previous["months"] += 1
            for evidence in month["evidence"]:
                if evidence["source"] not in previous["sources"]:
                    previous["sources"].append(dict(evidence["source"]))
        else:
            previous = None
        counts[month["requirement_id"]] += 1
    return notes


def _allocation(entry, workbook):
    review = entry["review"]
    target = review.get("target")
    reasons = []
    if not entry["identity_safe"]:
        reasons.append("unsafe_identity")
    if review["status"] not in {"automatic_match", "label_confirmed", "reviewed", "credit_review_required"} or target is None:
        reasons.extend(review.get("reasons", []) or ["unresolved_history"])
    reasons.extend(reason for reason in review.get("reasons", []) if reason != "remediation_credit_review")
    if reasons:
        return {"status": "pending", "reasons": sorted(set(reasons))}
    year = review.get("requirement_year") or target["residency_year"]
    years = recorded_years(entry["recorded_year"])
    target_year = year.strip().casefold()
    if not review.get("requirement_year") and (not years or target_year > max(years)):
        return {"status": "pending", "reasons": ["requirement_year_unconfirmed"]}
    validation = validate_posting(year, target, workbook.get("postings", {}).get("electives", []),
                                  core_catalogue=workbook.get("postings", {}).get("core", []))
    if not validation["valid"]:
        return {"status": "pending", "reasons": validation["reasons"]}
    return {"status": "expected", "reasons": [], "requirement_id": validation["requirement_id"],
            "requirement_year": year, "posting": validation["posting"], "institution": validation["institution"],
            "target": target, "progress_key": validation["progress_key"]}


def _summaries(months):
    counts = defaultdict(int)
    groups = []
    active = None
    previous = None
    for month in months:
        number = month_number(month["month"])
        if previous is not None and number != previous + 1:
            active = None
        previous = number
        if month["status"] == "loa":
            continue
        if month["status"] != "expected":
            active = None
            continue
        key = month["requirement_id"]
        counts[key] += 1
        if key != "r3.continuity_clinic":
            active = None
            continue
        progress_key = month["progress_key"]
        if active is None or active["progress_key"] != progress_key:
            active = {"progress_key": progress_key, "posting": month["posting"],
                      "institution": month["institution"], "start": month["month"], "end": month["month"], "expected_months": 0}
            groups.append(active)
        active["expected_months"] += 1
        active["end"] = month["month"]
    combined = PROGRAMME_REQUIREMENTS["R5"]["Child and Geriatric Psychiatry"]
    # As with R1's combined route, partial history belongs to the combined
    # block, not an assumed split between its components.
    if counts[combined["id"]] >= combined["months"]:
        for part in PROGRAMME_REQUIREMENTS["R5"].values():
            if part["id"] in combined["credits"]:
                counts[part["id"]] += part["months"]
    result = []
    for year, requirements in PROGRAMME_REQUIREMENTS.items():
        for posting, rule in requirements.items():
            count = counts[rule["id"]]
            if year == "R3":
                count = max((group["expected_months"] for group in groups), default=0)
            item = {"requirement_id": rule["id"], "requirement_year": year, "posting": posting,
                    "required_months": rule["months"], "expected_months": count,
                    "remaining_months": max(0, rule["months"] - count),
                    "evidence_status": "not_evidenced" if not count else "supported" if count >= rule["months"] else "partial"}
            if rule.get("credits"):
                item["alternative"] = True
                item["credits"] = list(rule["credits"])
                # A completed separate route also removes the need for a combined block.
                if all(counts[part["id"]] >= part["months"]
                       for part in PROGRAMME_REQUIREMENTS["R5"].values() if part["id"] in rule["credits"]):
                    item["remaining_months"] = 0
            if year == "R3":
                item["continuity_groups"] = groups
            result.append(item)
    return result
