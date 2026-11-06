"""R5 requirements and the supported six-month elective scope."""
from .r2_rules import partial_posting_identity

if __package__ == "backend.rules":
    from ..requirement_ledger import month_number
else:
    from requirement_ledger import month_number


def supported_option(option):
    remarks = option["remarks"] or []
    if not remarks:
        return True
    return option["category"] == "elective" and all(
        r["text"].strip().casefold() == "(all required 6 months duration)" for r in remarks)


def prepare_blocks(person, options, planning_start, earlier_months, blockers):
    blocks = []
    for requirement in person["requirements"]:
        if requirement["requirement_year"] != "R5" or not requirement["remaining_months"]:
            continue
        key = requirement["requirement_id"]
        try:
            partial = partial_posting_identity(person, key)
        except ValueError:
            blockers.append({"code": "conflicting_partial_r5_history", "source": person["source"]})
            continue
        if partial:
            history = [m for m in person["months"] if m["status"] == "expected" and m.get("requirement_id") == key]
            first = month_number(history[0]["month"])
            tail = [m for m in person["months"] if month_number(m["month"]) >= first]
            expected = first
            for month in tail:
                if month_number(month["month"]) != expected or not (
                        month["status"] == "loa" or month["status"] == "expected" and month.get("requirement_id") == key):
                    break
                expected += 1
            if earlier_months or expected != month_number(planning_start):
                blockers.append({"code": "conflicting_partial_r5_history", "source": person["source"]})
                continue
        eligible = [o for o in options if o["requirement_id"] == key
                    and (partial is None or (o["posting"], o["institution"]) == partial)]
        if not eligible:
            blockers.append({"code": "missing_r5_catalogue_option", "source": person["source"], "requirement_id": key})
        blocks.append((requirement, eligible, partial is not None))
    if sum(partial for _, _, partial in blocks) > 1:
        blockers.append({"code": "conflicting_partial_r5_history", "source": person["source"]})
    return blocks
