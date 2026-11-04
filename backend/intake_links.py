"""Explicit, browser-owned links between incoming residents and intake slots."""
from copy import deepcopy
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

if __package__:
    from .workbook_import import fill_intake_vacancies, intake_slot_id, normalized_label, review_import
else:
    from workbook_import import fill_intake_vacancies, intake_slot_id, normalized_label, review_import


class LinkModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SlotMonth(LinkModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    value: str | None = Field(max_length=2000)
    status: Literal["blank", "loa", "posting"]
    source: dict

    @model_validator(mode="after")
    def validate_month(self):
        date.fromisoformat(self.month + "-01")
        label = normalized_label(self.value)
        expected = "blank" if not label else "loa" if label == "loa" else "posting"
        ref = self.source
        physical = (set(ref) <= {"sheet", "row", "column"} and isinstance(ref.get("sheet"), str)
                    and bool(ref["sheet"].strip()) and type(ref.get("row")) is int and ref["row"] > 0
                    and ("column" not in ref or isinstance(ref["column"], str)))
        generated = (set(ref) == {"kind", "slot_id"} and ref["kind"] == "intake_placeholder"
                     and isinstance(ref["slot_id"], str))
        if expected != self.status or not (physical or generated):
            raise ValueError("Invalid slot posting status or source")
        return self


class IntakeLink(LinkModel):
    year: int = Field(ge=1900, le=9998)
    slot_id: str = Field(max_length=100)
    mcr: str = Field(min_length=1, max_length=2000)
    name: str = Field(min_length=1, max_length=2000)
    postings: list[SlotMonth] = Field(max_length=12)

    @model_validator(mode="after")
    def validate_link(self):
        prefix = f"intake-{self.year}-slot-"
        number = self.slot_id.removeprefix(prefix)
        if (not number.isascii() or not number.isdigit() or int(number) < 1
                or self.slot_id != f"{prefix}{int(number):02d}"
                or not self.mcr.strip() or not self.name.strip()):
            raise ValueError("Invalid intake slot or resident identity")
        months = set()
        for posting in self.postings:
            if (not f"{self.year}-07" <= posting.month <= f"{self.year + 1}-06" or posting.month in months
                    or (posting.source.get("kind") and posting.source["slot_id"] != self.slot_id)):
                raise ValueError("Slot months must be unique and within the linked intake year")
            months.add(posting.month)
        return self


class IntakeLinkStore(LinkModel):
    version: Literal[1]
    links: list[IntakeLink] = Field(max_length=500)

    @model_validator(mode="after")
    def unique_links(self):
        slots, people = set(), set()
        for link in self.links:
            slot, person = (link.year, link.slot_id), (link.year, normalized_label(link.mcr))
            if slot in slots or person in people:
                raise ValueError("Duplicate or conflicting intake links; nothing was imported")
            slots.add(slot)
            people.add(person)
        return self


def apply_intake_links(workbook, store):
    result = deepcopy(workbook)
    year = int(result["months"][0]["month"][:4])
    annual = next(sheet for sheet in result["annual_sheets"] if sheet["sheet"] == result["target_sheet"])
    result["residents"] = [deepcopy(row) for row in annual["residents"]]
    review_import(result)
    blocked = [record["source"] for issue in result["issues"]
               if issue["code"] in {"missing_mcr", "missing_name", "duplicate_mcr", "conflicting_identity", "duplicate_intake_placeholder"}
               for record in issue.get("records", [])]
    states = []
    for link in store.links:
        state = {"slot_id": link.slot_id, "year": link.year, "mcr": link.mcr, "name": link.name,
                 "status": "other_year", "message": "Saved for another planning year."}
        states.append(state)
        if link.year != year:
            continue
        people = [row for row in result["residents"] if normalized_label(row.get("mcr")) == normalized_label(link.mcr)]
        person = people[0] if len(people) == 1 else None
        slots = [row for row in result["residents"] if intake_slot_id(row, year) == link.slot_id]
        reason = None
        if (person is None or normalized_label(person.get("name")) != normalized_label(link.name)
                or normalized_label(person.get("residency_year")) != "r1"
                or (person.get("intake") or "").strip() != str(year)):
            reason = "Resident identity or intake changed or is missing. Remove this link and review the workbook."
        elif person["source"] in blocked or len(slots) > 1 or any(slot["source"] in blocked for slot in slots):
            reason = "Resolve duplicate or conflicting identities in Issues before applying this link."
        merged = {posting["month"]: deepcopy(posting) for posting in person["postings"]} if person else {}
        if reason is None:
            for posting in [p.model_dump() for p in link.postings] + (slots[0]["postings"] if slots else []):
                current = merged[posting["month"]]
                if current["status"] != "blank" and posting["status"] != "blank" and (
                        current["status"] != posting["status"] or normalized_label(current["value"]) != normalized_label(posting["value"])):
                    reason = "Slot and resident postings conflict. Review the workbook or remove this link; no postings were overwritten."
                    break
                if current["status"] == "blank" and posting["status"] != "blank":
                    merged[posting["month"]] = deepcopy(posting)
        if reason:
            state.update(status="needs_review", message=reason)
            continue
        person["slot_id"] = link.slot_id
        person["postings"] = list(merged.values())
        if slots:
            result["residents"].remove(slots[0])
        state.update(status="applied", message="Linked in this planning roster. Original annual records are unchanged.")
    # Recalculate the incoming count after collapsing links, then fill vacancies.
    review_import(result)
    fill_intake_vacancies(result)
    result["intake_links"] = states
    return result
