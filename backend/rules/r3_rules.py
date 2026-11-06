"""Continuity Clinic scheduling rules."""

def prepare_block(person, options, blockers):
    requirement = next(r for r in person["requirements"] if r["requirement_id"] == "r3.continuity_clinic")
    if not requirement["remaining_months"]:
        return []
    groups = requirement["continuity_groups"]
    partial = bool(requirement["expected_months"])
    # Preserve recognised credit despite later postings or gaps. Multiple
    # historical runs still need review; do not combine them automatically.
    if partial and len(groups) != 1:
        blockers.append({"code": "conflicting_partial_r3_history", "source": person["source"]})
        return []
    eligible = [o for o in options if o["requirement_id"] == requirement["requirement_id"]
                and (not partial or (o["posting"], o["institution"]) == (groups[0]["posting"], groups[0]["institution"]))]
    if not eligible:
        blockers.append({"code": "missing_r3_catalogue_option", "source": person["source"], "requirement_id": requirement["requirement_id"]})
    return [(requirement, eligible, partial)]
