"""Prepare fresh planning inputs without assigning postings or modifying evidence."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

if __package__:
    from .programme_requirements import validate_posting
    from .requirement_ledger import build_requirement_ledger, source_key
    from .workbook_import import normalized_label, posting_catalogue, recorded_years
else:
    from programme_requirements import validate_posting
    from requirement_ledger import build_requirement_ledger, source_key
    from workbook_import import normalized_label, posting_catalogue, recorded_years


def _integer(value, minimum):
    if value is None or isinstance(value, str) and not value.strip():
        return None
    try:
        number = Decimal(str(value))
        if number.is_finite() and number == int(number) and number >= minimum:
            return int(number)
    except (InvalidOperation, ValueError, OverflowError):
        pass
    raise ValueError("invalid integer")


def prepare_scheduler_inputs(workbook, reviewstore):
    """Compose importer and ledger data for a new schedule from the latest upload.

    workbook is the parsed importer result (including its validated July-June
    headings and filled intake slots). input_ready means usable inputs, not a feasible or generation-ready
    schedule. policy_reviews retain unsupported remarks which must be addressed
    before a solver uses those options. Recorded R-year never grants completion.
    """
    ledger = build_requirement_ledger(workbook, reviewstore)
    options, catalogue_blockers, policy_reviews, catalogue_summaries = [], [], [], []
    postings = workbook.get("postings", {})
    for category, rows in (("core", postings.get("core", [])), ("elective", postings.get("electives", []))):
        for row in rows:
            if (category == "core" and not normalized_label(row.get("posting"))
                    and all(row.get(field) is None or isinstance(row.get(field), str) and not row[field].strip()
                            for field in ("duration_months", "max", "remarks"))):
                continue
            # Elective summary rows describe the requirement; institution-specific
            # options come from the elective catalogue below.
            if category == "core" and normalized_label(row.get("posting")) in {"elective", "electives"}:
                catalogue_summaries.append(deepcopy(row))
                if row.get("remarks"):
                    policy_reviews.append({"code": "unsupported_posting_remarks", "source": deepcopy(row["source"]),
                                           "label": row["posting"], "remarks": deepcopy(row["remarks"])})
                continue
            targets = posting_catalogue({"core" if category == "core" else "electives": [row]})
            target = targets[0] if targets else {"category": category, "residency_year": row.get("residency_year"), "label": None, "source": row["source"]}
            validation = validate_posting(row.get("residency_year"), target, postings.get("electives", []),
                                          core_catalogue=postings.get("core", []))
            reasons = list(validation["reasons"])
            duration, capacity = None, None
            try:
                duration = _integer(row.get("duration_months"), 1) if category == "core" else validation["required_months"]
                if duration is None:
                    reasons.append("missing_duration")
                elif validation["valid"] and duration != validation["required_months"]:
                    reasons.append("programme_duration_mismatch")
            except ValueError:
                reasons.append("invalid_duration")
            try:
                capacity = _integer(row.get("max"), 0)
            except ValueError:
                reasons.append("invalid_capacity")
            option = {**target, **{key: validation[key] for key in (
                "requirement_id", "required_months", "institution", "posting", "training_months", "progress_key", "continuity")},
                "duration_months": duration, "capacity": capacity, "raw": deepcopy(row),
                "remarks": deepcopy(row.get("remarks")), "policy_review_required": bool(row.get("remarks")),
                "valid": not reasons, "reasons": reasons}
            options.append(option)
            catalogue_blockers.extend({"code": reason, "source": deepcopy(row["source"])} for reason in reasons)
            if option["policy_review_required"]:
                policy_reviews.append({"code": "unsupported_posting_remarks", "source": deepcopy(row["source"]),
                                       "label": target["label"], "remarks": deepcopy(row["remarks"])})

    residents = []
    for raw, progress in zip(workbook.get("residents", []), ledger["residents"]):
        blockers = [{"code": warning, "source": deepcopy(raw["source"])} for warning in progress["warnings"]]
        years = recorded_years(raw.get("residency_year"))
        if not years:
            blockers.append({"code": "recorded_year_unknown", "source": deepcopy(raw["source"])})
        incoming = normalized_label(raw.get("residency_year")) == "r1" and (raw.get("intake") or "").strip() == ledger["planning_start"][:4]
        if progress["identity_safe"] and not incoming and not progress["months"]:
            blockers.append({"code": "historical_progress_unknown", "source": deepcopy(raw["source"])})
        for month in progress["months"]:
            if month["status"] == "pending":
                blockers.extend({"code": reason, "month": month["month"],
                                 "sources": [deepcopy(e["source"]) for e in month["evidence"]]}
                                for reason in month["reasons"])
        for issue in workbook.get("issues", []):
            if issue.get("code") in {"unclear_intake", "excess_intake", "duplicate_intake_placeholder", "intake_fill_blocked"} and (
                    any(source_key(r["source"])[:2] == source_key(raw["source"])[:2] for r in issue.get("records", []))
                    or issue.get("source") == raw["source"]):
                blockers.append({"code": issue["code"], "source": deepcopy(issue.get("source", raw["source"]))})
        availability = []
        for month in workbook["months"]:
            entries = [p for p in raw.get("postings", []) if p["month"] == month["month"]]
            unavailable = any(p["status"] == "loa" for p in entries)
            invalid = len(entries) != 1 or any(p["status"] not in {"loa", "blank", "posting"} for p in entries)
            if invalid:
                blockers.append({"code": "invalid_planning_month_evidence", "month": month["month"], "source": deepcopy(raw["source"])})
            availability.append({"month": month["month"], "available": not unavailable and not invalid,
                                 "reason": "invalid_evidence" if invalid else "loa" if unavailable else None, "evidence": deepcopy(entries)})
        residents.append({**deepcopy(progress), "intake": raw.get("intake"), "remarks": raw.get("remarks"),
                          "recorded_years": sorted(years), "availability": availability, "blockers": blockers, "input_ready": not blockers})
    blockers = catalogue_blockers
    if not residents:
        blockers.append({"code": "empty_roster"})
    if not options:
        blockers.append({"code": "empty_catalogue"})
    return {"planning_months": deepcopy(workbook["months"]), "planning_start": ledger["planning_start"],
            "cutoff": ledger["cutoff"], "basis": ledger["basis"], "residents": residents,
            "catalogue_options": options, "catalogue_summaries": catalogue_summaries,
            "policy_reviews": policy_reviews, "blockers": blockers,
            "requests": deepcopy(workbook.get("requests", [])), "import_issues": deepcopy(workbook.get("issues", [])),
            "input_ready": not blockers and all(r["input_ready"] for r in residents)}
