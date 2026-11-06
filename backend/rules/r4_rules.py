"""R4 blocks and eligibility using recognised historical credit."""

from .r2_rules import partial_posting_identity
if __package__ == "backend.rules":
    from ..programme_requirements import PROGRAMME_REQUIREMENTS
    from ..requirement_ledger import month_number
else:
    from programme_requirements import PROGRAMME_REQUIREMENTS
    from requirement_ledger import month_number


def prepare_blocks(person, options, planning_start, earlier_months, blockers):
    blocks = []
    remaining = [r for r in person["requirements"] if r["requirement_year"] == "R4" and r["remaining_months"]]
    if not remaining and person["cluster_coverage"]["missing"]:
        blockers.append({"code": "completed_r4_missing_clusters", "source": person["source"],
                         "clusters": person["cluster_coverage"]["missing"]})
    imh = sum(
        m["status"] == "expected" and m.get("requirement_id") == "r1.inpatient_psychiatry"
        and m["institution"] == "IMH" for m in person["months"]) >= PROGRAMME_REQUIREMENTS["R1"]["Inpatient Psychiatry"]["months"]
    for requirement in person["requirements"]:
        if requirement["requirement_year"] != "R4" or not requirement["remaining_months"]:
            continue
        key = requirement["requirement_id"]
        try:
            partial = partial_posting_identity(person, key)
        except ValueError:
            blockers.append({"code": "conflicting_partial_r4_history", "source": person["source"]})
            continue
        if partial:
            history = [m for m in person["months"] if m["status"] == "expected" and m.get("requirement_id") == key]
            first, last = month_number(history[0]["month"]), month_number(history[-1]["month"])
            tail = [m for m in person["months"] if month_number(m["month"]) >= first]
            expected = first
            for month in tail:
                if month_number(month["month"]) != expected or not (
                        month["status"] == "loa" or month["status"] == "expected" and month.get("requirement_id") == key):
                    break
                expected += 1
            if earlier_months or expected != month_number(planning_start) or last >= expected:
                blockers.append({"code": "conflicting_partial_r4_history", "source": person["source"]})
                continue
        eligible = [o for o in options if o["requirement_id"] == key
                    and (partial is None or (o["posting"], o["institution"]) == partial)
                    and not (imh and key == "r4.inpatient_psychiatry" and o["institution"] == "IMH")]
        if not eligible:
            blockers.append({"code": "missing_r4_catalogue_option", "source": person["source"], "requirement_id": key})
        blocks.append((requirement, eligible, partial is not None))
    if sum(partial for _, _, partial in blocks) > 1:
        blockers.append({"code": "conflicting_partial_r4_history", "source": person["source"]})
    return blocks
