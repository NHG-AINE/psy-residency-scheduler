"""Continuous R2 posting blocks, preserving recognised partial history."""


def partial_posting_identity(person, requirement_id):
    """Return (posting, institution) for unambiguous partial recognised credit.

    Completion requires no continuation. Distinct historical postings or sites
    are unsafe to combine into one continuous remaining block.
    """
    requirement = next(item for item in person["requirements"]
                       if item["requirement_id"] == requirement_id)
    if not requirement["expected_months"] or not requirement["remaining_months"]:
        return None
    identities = {(month["posting"], month["institution"]) for month in person["months"]
                  if month["status"] == "expected" and month.get("requirement_id") == requirement_id}
    if len(identities) != 1:
        raise ValueError("conflicting_partial_r2_history")
    return next(iter(identities))


def prepare_blocks(person, options, blockers):
    blocks = []
    for requirement in person["requirements"]:
        if requirement["requirement_year"] != "R2" or not requirement["remaining_months"]:
            continue
        key = requirement["requirement_id"]
        try:
            partial = partial_posting_identity(person, key)
        except ValueError:
            blockers.append({"code": "conflicting_partial_r2_history", "source": person["source"]})
            continue
        eligible = [o for o in options if o["requirement_id"] == key
                    and (partial is None or (o["posting"], o["institution"]) == partial)]
        if not eligible:
            blockers.append({"code": "missing_r2_catalogue_option", "source": person["source"], "requirement_id": key})
        blocks.append((requirement, eligible, partial is not None))
    if sum(partial for _, _, partial in blocks) > 1:
        blockers.append({"code": "conflicting_partial_r2_history", "source": person["source"]})
    return blocks


def add_blocks(model, person, blocks, r1_months, resident_index):
    """Schedule on active training-month indices, so LOA pauses all blocks.

    The virtual tail records carryforward only; no future calendar capacity or
    cluster credit is claimed beyond the planning horizon.
    """
    active = [i for i, m in enumerate(person["availability"]) if m["available"]]
    end = r1_months + sum(r["remaining_months"] for r, _, _ in blocks)
    coverage = {tick: [] for tick in range(r1_months, end)}
    placements = []
    for requirement, options, partial in blocks:
        length = requirement["remaining_months"]
        choices = []
        starts = [r1_months] if partial else range(r1_months, end - length + 1)
        for start in starts:
            for option in options:
                variable = model.new_bool_var(f"r2_{resident_index}_{len(placements)}")
                choices.append(variable)
                for tick in range(start, start + length):
                    coverage[tick].append(variable)
                months = [active[tick] for tick in range(start, start + length) if tick < len(active)]
                placements.append({"variable": variable, "option": option, "months": months,
                                   "remaining": length - len(months)})
        model.add_exactly_one(choices)
    for variables in coverage.values():
        model.add_exactly_one(variables)
    return placements
