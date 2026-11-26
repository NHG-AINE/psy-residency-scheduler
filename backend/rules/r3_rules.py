"""Continuity Clinic scheduling rules."""

def prepare_block(person, options, blockers):
    requirement = next(r for r in person["requirements"] if r["requirement_id"] == "r3.continuity_clinic")
    if not requirement["remaining_months"]:
        return []
    identities = {(group["posting"], group["institution"]) for group in requirement["continuity_groups"]}
    if len(identities) > 1:
        blockers.append({"code": "conflicting_partial_r3_history", "source": person["source"]})
        return []
    eligible = [o for o in options if o["requirement_id"] == requirement["requirement_id"]
                and (not identities or (o["posting"], o["institution"]) in identities)]
    if not eligible:
        blockers.append({"code": "missing_r3_catalogue_option", "source": person["source"], "requirement_id": requirement["requirement_id"]})
    return [(requirement, eligible, bool(identities))]
