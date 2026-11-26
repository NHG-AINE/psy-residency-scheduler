"""R4 blocks and eligibility using recognised historical credit."""

from .r2_rules import partial_posting_identity
if __package__ == "backend.rules":
    from ..programme_requirements import PROGRAMME_REQUIREMENTS
else:
    from programme_requirements import PROGRAMME_REQUIREMENTS


def completed_r1_inpatient_at_imh(person, planned_months=0):
    return planned_months + sum(
        m["status"] == "expected" and m.get("requirement_id") == "r1.inpatient_psychiatry"
        and m["institution"] == "IMH" for m in person["months"]) >= PROGRAMME_REQUIREMENTS["R1"]["Inpatient Psychiatry"]["months"]


def prepare_blocks(person, options, blockers):
    blocks = []
    imh = completed_r1_inpatient_at_imh(person)
    for requirement in person["requirements"]:
        if requirement["requirement_year"] != "R4" or not requirement["remaining_months"]:
            continue
        key = requirement["requirement_id"]
        try:
            partial = partial_posting_identity(person, key)
        except ValueError:
            blockers.append({"code": "conflicting_partial_r4_history", "source": person["source"]})
            continue
        eligible = [o for o in options if o["requirement_id"] == key
                    and (partial is None or (o["posting"], o["institution"]) == partial)
                    and not (imh and key == "r4.inpatient_psychiatry" and o["institution"] == "IMH")]
        if not eligible:
            blockers.append({"code": "missing_r4_catalogue_option", "source": person["source"], "requirement_id": key})
        blocks.append((requirement, eligible, partial is not None))
    return blocks
