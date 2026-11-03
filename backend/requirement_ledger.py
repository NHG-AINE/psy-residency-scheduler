"""Expected programme progress from workbook evidence; never certified training credit."""
from collections import defaultdict
from datetime import date

if __package__:
    from .history_review import evaluate_review, mcr_key
    from .programme_requirements import PROGRAMME_REQUIREMENTS, R1_COMPLETION_ROUTES, validate_posting
    from .workbook_import import normalized_label, recorded_years
else:
    from history_review import evaluate_review, mcr_key
    from programme_requirements import PROGRAMME_REQUIREMENTS, R1_COMPLETION_ROUTES, validate_posting
    from workbook_import import normalized_label, recorded_years


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

    def safe(resident):
        return bool(mcr_key(resident.get("mcr")) and normalized_label(resident.get("name"))
                    and source_key(resident.get("source", {}))[:2] not in blocked
                    and ("annual_sheets" in workbook or resident.get("match_status") != "ambiguous"))

    resolved = defaultdict(list)
    for entry in evaluate_review(workbook, store)["entries"]:
        for month, source in zip(entry["months"], entry["sources"]):
            resolved[(mcr_key(entry["mcr"]), normalized_label(entry["name"]), month["month"], source_key(source))].append(entry)
    annual = workbook.get("annual_sheets", workbook.get("histories", []) + [{"residents": workbook.get("residents", [])}])
    raw = defaultdict(lambda: defaultdict(list))
    unsafe_history = set()
    for sheet in annual:
        for resident in sheet["residents"]:
            identity = (mcr_key(resident.get("mcr")), normalized_label(resident.get("name")))
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
                    entries = resolved.get((*identity, month, source_key(posting["source"])), [])
                    outcomes = [_allocation(entry, workbook) for entry in entries]
                    outcome = outcomes[0] if outcomes and all(item == outcomes[0] for item in outcomes) else {
                        "status": "pending", "reasons": ["unresolved_history"]}
                raw[identity][month].append((evidence, outcome))
    residents = []
    for resident in workbook.get("residents", []):
        identity = (mcr_key(resident.get("mcr")), normalized_label(resident.get("name")))
        identity_safe = safe(resident)
        months = []
        for month, values in sorted(raw[identity].items()) if identity_safe else []:
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
                          "recorded_year": resident.get("residency_year"), "source": resident["source"],
                          "identity_safe": identity_safe,
                          "warnings": (["unsafe_identity"] if not identity_safe else [])
                          + (["unsafe_historical_identity_evidence_excluded"] if identity in unsafe_history else []),
                          "months": months, "requirements": summaries, "r1_routes": routes})
    return {"planning_start": start, "cutoff": cutoff, "basis": "projected_expected_not_certified", "residents": residents}


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
    validation = validate_posting(year, target, workbook.get("postings", {}).get("electives", []))
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
            if year == "R3":
                item["continuity_groups"] = groups
            result.append(item)
    return result
