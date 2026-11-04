"""Read-only evaluation of browser-owned historical review decisions."""
from collections import defaultdict
from datetime import date
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

if __package__:
    from .workbook_import import match_posting, normalized_label, posting_catalogue, recorded_years
else:
    from workbook_import import match_posting, normalized_label, posting_catalogue, recorded_years

Text = Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Target(ReviewModel):
    key: Text
    signature: Text


class MonthValue(ReviewModel):
    month: Annotated[str, StringConstraints(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
    value: Text


class ResidentContext(ReviewModel):
    mcr: Text
    name: Text
    recorded_year: Annotated[str, StringConstraints(max_length=2000)]
    months: Annotated[list[MonthValue], Field(min_length=1, max_length=120)]


class AliasContext(ReviewModel):
    label: Text
    recorded_year: Annotated[str, StringConstraints(max_length=2000)]
    category: Literal["core", "elective"]


class ResidentDecision(ReviewModel):
    kind: Literal["resident"]
    context: ResidentContext
    target: Target
    requirement_year: Literal["R1", "R2", "R3", "R4", "R5"] | None = None


class AliasDecision(ReviewModel):
    kind: Literal["alias"]
    context: AliasContext
    target: Target


Decision = Annotated[ResidentDecision | AliasDecision, Field(discriminator="kind")]


class ReviewStore(ReviewModel):
    version: Literal[1]
    decisions: Annotated[list[Decision], Field(max_length=5000)]


def content_key(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def mcr_key(value):
    return " ".join((value or "").split()).upper()


def decision_key(decision):
    context = decision["context"]
    if decision["kind"] == "alias":
        return content_key(["alias", normalized_label(context["label"]),
                            normalized_label(context["recorded_year"]), context["category"]])
    return content_key(["resident", mcr_key(context["mcr"]),
                        sorted([[m["month"], m["value"]] for m in context["months"]])])


def catalogue_entries(postings):
    catalogue = posting_catalogue(postings)
    rows = [r for r in postings.get("core", []) if r.get("posting")] + postings.get("electives", [])
    for candidate, row in zip(catalogue, rows):
        candidate["key"] = content_key([candidate["category"], normalized_label(candidate["residency_year"]),
                                        normalized_label(candidate["label"])])
        remarks = row.get("remarks")
        if isinstance(remarks, list):
            remarks = [r["text"] for r in remarks]
        candidate["signature"] = content_key([candidate["key"], row.get("duration_months"),
                                              row.get("max"), remarks])
    return catalogue


def consecutive(left, right):
    year, month = map(int, left.split("-"))
    return right == f"{year + month // 12:04d}-{month % 12 + 1:02d}"


def posting_entries(workbook, scope: Literal["history", "timetable"] = "history"):
    """Only safe identities may join across sheets; separated runs stay separate."""
    blocked = set()
    for issue in workbook.get("issues", []):
        if issue["code"] in {"missing_mcr", "missing_name", "duplicate_mcr", "conflicting_identity"}:
            blocked.update((r["source"]["sheet"], r["source"]["row"]) for r in issue.get("records", []))
    groups = defaultdict(list)
    annual = [{"residents": workbook["residents"]}] if scope == "timetable" else workbook.get("annual_sheets", workbook["histories"])
    for history in annual:
        for resident in history["residents"]:
            if resident["source"].get("kind") == "intake_placeholder":
                continue
            ref = resident["source"]
            safe = bool(mcr_key(resident.get("mcr")) and normalized_label(resident.get("name"))
                        and ("annual_sheets" in workbook or resident.get("match_status") != "ambiguous")
                        and (ref["sheet"], ref["row"]) not in blocked)
            identity = [mcr_key(resident.get("mcr")), normalized_label(resident.get("name")),
                        normalized_label(resident.get("residency_year"))]
            group = content_key(identity if safe else identity + [ref])
            for posting in resident["postings"]:
                # Validate dates at this API boundary before sorting/grouping them.
                date.fromisoformat(posting["month"] + "-01")
                groups[group].append((resident, posting, safe))
    entries = []
    for monthly in groups.values():
        previous = None
        for resident, posting, safe in sorted(monthly, key=lambda row: row[1]["month"]):
            if posting["status"] != "posting":
                previous = None
                continue
            if (previous and consecutive(previous["months"][-1]["month"], posting["month"])
                    and previous["months"][-1]["value"] == posting["value"]):
                previous["months"].append({"month": posting["month"], "value": posting["value"]})
                previous["sources"].append(posting["source"])
                continue
            previous = {"name": resident.get("name"), "mcr": resident.get("mcr"),
                        "recorded_year": resident.get("residency_year"), "identity_safe": safe,
                        "months": [{"month": posting["month"], "value": posting["value"]}],
                        "sources": [posting["source"]]}
            entries.append(previous)
    for index, entry in enumerate(entries):
        entry["context"] = {"mcr": mcr_key(entry["mcr"]), "name": normalized_label(entry["name"]),
                            "recorded_year": normalized_label(entry["recorded_year"]), "months": entry["months"]}
        entry["key"] = decision_key({"kind": "resident", "context": entry["context"]})
        entry["id"] = content_key([entry["key"], entry["sources"], index])
    return entries


def evaluate_review(workbook, store, scope: Literal["history", "timetable"] = "history"):
    catalogue = catalogue_entries(workbook["postings"])
    targets = defaultdict(list)
    for candidate in catalogue:
        targets[candidate["key"]].append(candidate)
    entries = posting_entries(workbook, scope)
    decisions = [d.model_dump() for d in store.decisions]
    by_key = defaultdict(list)
    for decision in decisions:
        by_key[decision_key(decision)].append(decision)
    states = []
    for decision in decisions:
        key = decision_key(decision)
        found = targets[decision["target"]["key"]]
        target = found[0] if len(found) == 1 else None
        reasons = []
        if len(by_key[key]) > 1:
            reasons.append("conflicting_saved_decisions")
        if target is None or target["signature"] != decision["target"]["signature"]:
            reasons.append("catalogue_target_changed_or_missing")
        if decision["kind"] == "resident" and decision.get("requirement_year") and target:
            if normalized_label(decision["requirement_year"]) not in recorded_years(target["residency_year"]):
                reasons.append("incompatible_requirement_year")
        if decision["kind"] == "alias" and target and decision["context"]["category"] != target["category"]:
            reasons.append("incompatible_alias_category")
        states.append({"key": key, "decision": decision, "target": target,
                       "status": "needs_review" if reasons else "not_present", "reasons": list(reasons), "_base_reasons": reasons})
    for entry in entries:
        posting = {"value": entry["months"][0]["value"], "status": "posting"}
        match = match_posting(posting, entry["recorded_year"], catalogue)
        entry["match"] = match
        entry["review"] = {"status": "unreviewed", "target": None, "requirement_year": None, "reasons": []}
        applicable = []
        for state in states:
            decision = state["decision"]
            period_changed = False
            if decision["kind"] == "resident":
                relevant = state["key"] == entry["key"]
                if not relevant and mcr_key(decision["context"]["mcr"]) == mcr_key(entry["mcr"]):
                    period_changed = bool({m["month"] for m in decision["context"]["months"]}
                                          & {m["month"] for m in entry["months"]})
                    relevant = period_changed
                context_ok = (decision["context"]["name"] == entry["context"]["name"]
                              and decision["context"]["recorded_year"] == entry["context"]["recorded_year"])
                safe = entry["identity_safe"]
            else:
                context = decision["context"]
                relevant = (normalized_label(context["label"]) == normalized_label(posting["value"])
                            and normalized_label(context["recorded_year"]) == entry["context"]["recorded_year"])
                context_ok, safe = True, True
                if "explicit_elective" in match["reasons"] and context["category"] != "elective":
                    context_ok = False
            if not relevant:
                continue
            errors = list(state["_base_reasons"])
            if period_changed:
                errors.append("recorded_period_changed")
            if not safe:
                errors.append("identity_review_required")
            if not context_ok:
                errors.append("recorded_context_changed")
            if ("explicit_elective" in match["reasons"] and state["target"]
                    and state["target"]["category"] != "elective"):
                errors.append("explicit_elective_target_required")
            if errors:
                state["status"] = "needs_review"
                state["reasons"] = list(dict.fromkeys(state["reasons"] + errors))
            else:
                if state["status"] != "needs_review":
                    state["status"] = "applied"
                applicable.append(state)
            entry["review"]["reasons"].extend(errors)
        personal = [s for s in applicable if s["decision"]["kind"] == "resident"]
        selected = personal or applicable
        # A resident decision may add a year to an alias, but may not silently contradict it.
        if len({s["target"]["key"] for s in applicable}) > 1:
            entry["review"]["reasons"].append("conflicting_saved_decisions")
            for state in applicable:
                state["status"] = "needs_review"
                if "conflicting_saved_decisions" not in state["reasons"]:
                    state["reasons"].append("conflicting_saved_decisions")
        elif selected and not entry["review"]["reasons"]:
            decision = selected[0]["decision"]
            requirement_year = decision.get("requirement_year")
            entry["review"].update(status="reviewed" if requirement_year else "label_confirmed",
                                   target=selected[0]["target"], requirement_year=requirement_year)
        if entry["review"]["reasons"]:
            entry["review"]["status"] = "needs_review"
        # Automatic recognition never replaces a saved decision or assigns credit/year.
        if (entry["review"]["status"] == "unreviewed" and not entry["review"]["reasons"]
                and match["status"] == "matched"):
            entry["review"].update(status="automatic_match", target=match["selected_candidate"])
        if "remediation_credit_review" in match["reasons"]:
            entry["review"]["reasons"].append("remediation_credit_review")
            if entry["review"]["status"] in {"reviewed", "automatic_match"}:
                entry["review"]["status"] = "credit_review_required"
    for state in states:
        state.pop("_base_reasons")
        if state["status"] == "not_present":
            state["reasons"].append("not_present_in_this_import")
    return {"entries": entries, "catalogue": catalogue, "decisions": states}
