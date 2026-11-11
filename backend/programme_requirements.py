"""Programme eligibility for resolved catalogue targets, never training credit.

Callers must supply a safely resolved candidate/manual target and a requirement
R-year, not substitute the resident's recorded/current R-year. A valid result
neither confirms that year nor authorizes credit for an identity, shared label
mapping or remediation entry. Credit and duration accounting belong elsewhere.
"""
if __package__:
    from .workbook_import import normalized_label, normalized_posting_label
else:
    from workbook_import import normalized_label, normalized_posting_label


PROGRAMME_REQUIREMENTS = {
    "R1": {
        "General Medicine": {"id": "r1.general_medicine", "months": 4,
                             "training_months": (1, 6)},
        "Neurology": {"id": "r1.neurology", "months": 2,
                      "training_months": (1, 6)},
        "Medicine & Neurology": {"id": "r1.medicine_neurology", "months": 6,
                                 "training_months": (1, 6)},
        "Inpatient Psychiatry": {"id": "r1.inpatient_psychiatry", "months": 6,
                                 "training_months": (7, 12)},
    },
    "R2": {
        "Elective": {"id": "r2.elective", "months": 3},
        "Geriatric Psychiatry": {"id": "r2.geriatric_psychiatry", "months": 3},
        "Child & Adolescent Psychiatry": {"id": "r2.child_adolescent_psychiatry", "months": 3},
        "Addiction Medicine": {"id": "r2.addiction_medicine", "months": 3},
    },
    "R3": {
        "Continuity Clinic": {
            "id": "r3.continuity_clinic", "months": 12,
            "continuity": {"same_posting": True, "same_institution": True, "loa": "pause"},
        },
    },
    "R4": {
        "Inpatient Psychiatry": {"id": "r4.inpatient_psychiatry", "months": 3},
        "Consultation Liaison Psychiatry": {"id": "r4.consultation_liaison_psychiatry", "months": 3},
        "Emergency Psychiatry": {"id": "r4.emergency_psychiatry", "months": 3},
        "Forensic Psychiatry": {"id": "r4.forensic_psychiatry", "months": 3},
    },
    "R5": {
        "Geriatric Psychiatry": {"id": "r5.geriatric_psychiatry", "months": 3},
        "Child & Adolescent Psychiatry": {"id": "r5.child_adolescent_psychiatry", "months": 3},
        "Elective": {"id": "r5.elective", "months": 6},
    },
}


# Complete either route, not every R1 entry above. Timing windows are inclusive
# months within R1, not calendar months; enforcement belongs to the scheduler.
R1_COMPLETION_ROUTES = (
    ("r1.general_medicine", "r1.neurology", "r1.inpatient_psychiatry"),
    ("r1.medicine_neurology", "r1.inpatient_psychiatry"),
)


def validate_posting(requirement_year, resolved_target, elective_catalogue=(), *, core_catalogue=()):
    """Validate requirements against programme rules and institutions against the workbook.

    Electives are the parsed catalogue rows (year, institution, elective), not
    raw history labels. Core institutions must also appear in the supplied catalogue.
    Workbook durations/remarks do not override the programme.
    R3 progress keys distinguish each posting option and institution; LOA policy
    is declarative only. This function does not consume months or compute totals.
    """
    year = requirement_year.strip().upper() if isinstance(requirement_year, str) else None
    result = {"valid": False, "requirement_year": year, "requirement_id": None,
              "required_months": None, "posting": None, "institution": None,
              "progress_key": None, "continuity": None, "training_months": None, "reasons": []}
    if year not in PROGRAMME_REQUIREMENTS:
        result["reasons"].append("unknown_requirement_year")
        return result
    if not isinstance(resolved_target, dict):
        result["reasons"].append("unresolved_catalogue_target")
        return result
    target_year = resolved_target.get("residency_year")
    if not isinstance(target_year, str) or target_year.strip().upper() not in PROGRAMME_REQUIREMENTS:
        result["reasons"].append("catalogue_year_not_specific")
        return result
    if target_year.strip().upper() != year:
        result["reasons"].append("catalogue_year_mismatch")
        return result
    category = resolved_target.get("category")
    if category not in {"core", "elective"}:
        result["reasons"].append("unknown_catalogue_category")
        return result
    label = resolved_target.get("label")
    parts = label.split(maxsplit=1) if isinstance(label, str) else []
    if len(parts) != 2:
        result["reasons"].append("invalid_catalogue_label")
        return result
    institution, posting = parts[0].upper(), " ".join(parts[1].split())
    result.update(institution=institution, posting=posting)
    requirement = None
    if category == "elective":
        requirement = PROGRAMME_REQUIREMENTS[year].get("Elective")
        if requirement is not None:
            rows = [row for row in elective_catalogue
                    if normalized_label(row.get("residency_year")) == year.casefold()
                    and normalized_posting_label(row.get("elective")) == normalized_posting_label(posting)]
            eligible = next((row for row in rows if normalized_label(row.get("institution")) == institution.casefold()), None)
            if not elective_catalogue:
                result["reasons"].append("elective_catalogue_missing")
            elif not rows:
                result["reasons"].append("elective_not_in_catalogue_for_year")
            elif eligible is None:
                result["reasons"].append("institution_not_allowed")
            else:
                result["posting"] = eligible["elective"]
    else:
        for name, candidate in PROGRAMME_REQUIREMENTS[year].items():
            if name == "Elective":
                continue
            if normalized_posting_label(name) == normalized_posting_label(posting):
                requirement = candidate
                result["posting"] = name
                if not any(normalized_label(row.get("residency_year")) == year.casefold()
                           and normalized_posting_label(row.get("posting")) == normalized_posting_label(label)
                           for row in core_catalogue):
                    result["reasons"].append("institution_not_allowed")
                break
    if requirement is None:
        result["reasons"].append("posting_not_required_for_year")
        return result
    result.update(requirement_id=requirement["id"], required_months=requirement["months"],
                  training_months=requirement.get("training_months"))
    result["valid"] = not result["reasons"]
    if result["valid"] and year == "R3":
        result["progress_key"] = (requirement["id"], result["posting"], institution)
        result["continuity"] = dict(requirement["continuity"])
    return result
