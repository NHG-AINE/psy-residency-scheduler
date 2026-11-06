"""Continuity Clinic scheduling rules."""

if __package__ == "backend.rules":
    from ..requirement_ledger import month_number
else:
    from requirement_ledger import month_number


def prepare_block(person, options, planning_start, earlier_months, blockers):
    requirement = next(r for r in person["requirements"] if r["requirement_id"] == "r3.continuity_clinic")
    if not requirement["remaining_months"]:
        return []
    groups = requirement["continuity_groups"]
    partial = bool(requirement["expected_months"])
    if partial:
        # Only an uninterrupted run ending at the planning cutoff can resume.
        tail = [m for m in person["months"] if m["month"] > groups[0]["end"]]
        consecutive = month_number(groups[0]["end"])
        for month in tail:
            consecutive += 1
            if month_number(month["month"]) != consecutive or month["status"] != "loa":
                break
        if (len(groups) != 1 or earlier_months or consecutive != month_number(planning_start) - 1
                or any(m["status"] != "loa" for m in tail)):
            blockers.append({"code": "conflicting_partial_r3_history", "source": person["source"]})
            return []
    eligible = [o for o in options if o["requirement_id"] == requirement["requirement_id"]
                and (not partial or (o["posting"], o["institution"]) == (groups[0]["posting"], groups[0]["institution"]))]
    if not eligible:
        blockers.append({"code": "missing_r3_catalogue_option", "source": person["source"], "requirement_id": requirement["requirement_id"]})
    return [(requirement, eligible, partial)]
