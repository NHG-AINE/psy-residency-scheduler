"""Read posting records without interpreting them as completed training or rules."""
from datetime import date, datetime
from collections import defaultdict
from io import BytesIO
import re
from zipfile import ZipFile

from openpyxl import load_workbook

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_EXPANDED_BYTES = 50 * 1024 * 1024


class WorkbookError(ValueError):
    pass


def text(value):
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def source(sheet, row, column=None):
    ref = {"sheet": sheet.title, "row": row}
    if column is not None:
        ref["column"] = column
    return ref


def header(sheet, required):
    for row in sheet.iter_rows(max_row=min(sheet.max_row, 10)):
        columns = {str(c.value).strip().lower(): c.column for c in row if c.value is not None}
        if required <= columns.keys():
            for merged in sheet.merged_cells.ranges:
                if merged.min_row <= row[0].row <= merged.max_row:
                    value = sheet.cell(merged.min_row, merged.min_col).value
                    if value is not None:
                        columns.setdefault(str(value).strip().lower(), merged.min_col)
            return row[0].row, columns
    raise WorkbookError(f"{sheet.title}: required headers missing: {', '.join(sorted(required))}")


def records(sheet, header_row, columns, fields):
    result = []
    for row in range(header_row + 1, sheet.max_row + 1):
        record = {field: text(sheet.cell(row, columns[label]).value) if label in columns else None
                  for field, label in fields.items()}
        if any(record.get(key) for key in ("name", "mcr", "residency_year", "posting")):
            record["source"] = source(sheet, row)
            result.append(record)
    return result


IDENTITY_FIELDS = {"name": "name", "mcr": "mcr no.", "residency_year": "residency year",
                   "intake": "residency intake", "mom_number": "mom number", "email": "email", "remarks": "remarks"}


def yearly_sheet(sheet):
    header_row, columns = header(sheet, {"name", "mcr no.", "residency year"})
    month_cells = []
    for row in sheet.iter_rows(max_row=header_row):
        dates = [c for c in row if isinstance(c.value, (date, datetime))]
        if len(dates) == 12:
            month_cells = dates
            break
    if not month_cells:
        raise WorkbookError(f"{sheet.title}: twelve calendar month headings are required")
    first = month_cells[0].value
    expected = [f"{first.year + (i + 6) // 12:04d}-{(i + 6) % 12 + 1:02d}" for i in range(12)]
    if first.month != 7 or [c.value.strftime("%Y-%m") for c in month_cells] != expected:
        raise WorkbookError(f"{sheet.title}: headings must run July through June in order")
    months = [{"month": c.value.strftime("%Y-%m"),
               "date_range_text": text(sheet.cell(header_row, c.column).value),
               "source": source(sheet, c.row, c.column_letter)} for c in month_cells]
    # The target sheet has merged SAF notes spanning the year. Retain the anchor
    # reference and text across its months; do not interpret the note as training.
    anchors = {}
    for merged in sheet.merged_cells.ranges:
        for row in range(merged.min_row, merged.max_row + 1):
            for col in range(merged.min_col, merged.max_col + 1):
                anchors[row, col] = (merged.min_row, merged.min_col)
    residents = records(sheet, header_row, columns, IDENTITY_FIELDS)
    for resident in residents:
        row = resident["source"]["row"]
        resident["postings"] = []
        for c, month in zip(month_cells, months):
            cell = sheet.cell(*anchors.get((row, c.column), (row, c.column)))
            value = text(cell.value)
            label = (value or "").strip().casefold()
            status = "blank" if not label else "loa" if label == "loa" else "posting"
            resident["postings"].append({"month": month["month"], "value": value, "status": status,
                                          "source": source(sheet, cell.row, cell.column_letter)})
    return {"year": first.year, "sheet": sheet.title, "months": months, "residents": residents}


def elective_catalogue(sheet, header_row, columns):
    """Extract reference labels and notes only; do not infer training credit."""
    electives = []
    for year in ("R2", "R5"):
        column = columns.get(f"{year.lower()} electives")
        if column is None:
            continue
        institution, institution_source, institution_notes, previous = None, None, [], None
        year_source = source(sheet, header_row, sheet.cell(header_row, column).column_letter)
        for row in range(header_row + 1, sheet.max_row + 1):
            cell = sheet.cell(row, column)
            raw = text(cell.value)
            label = (raw or "").strip()
            if not label:
                continue
            ref = source(sheet, row, cell.column_letter)
            heading = re.fullmatch(r"([A-Z][A-Z0-9]*)(?:\s*(\(.*\)))?", label, re.DOTALL)
            if heading:
                institution, institution_source = heading[1], ref
                institution_notes = ([{"text": raw[raw.index("("):], "source": ref}]
                                     if heading[2] else [])
                previous = None
            elif label.startswith(("-", "\u2022")) and institution and label[1:].strip():
                previous = {"residency_year": year, "institution": institution,
                            "elective": label[1:].strip(), "remarks": list(institution_notes),
                            "source": ref, "residency_year_source": year_source,
                            "institution_source": institution_source}
                electives.append(previous)
            elif label.startswith("("):
                if previous is not None:
                    previous["remarks"].append({"text": raw, "source": ref})
            else:
                institution, institution_source, institution_notes, previous = None, None, [], None
    return electives


def normalized_label(value):
    return " ".join((value or "").split()).casefold()


def recorded_years(value):
    return set(re.findall(r"\br[1-5]\b", normalized_label(value)))


def posting_catalogue(postings):
    """Keep catalogue source identities, including duplicate labels across years."""
    return [
        {"source": row["source"], "category": category,
         "residency_year": row.get("residency_year"), "label": label}
        for category, rows in (("core", postings.get("core", [])),
                               ("elective", postings.get("electives", [])))
        for row in rows
        if (label := (row.get("posting") if category == "core" else
                      f"{row['institution']} {row['elective']}"))
    ]


def match_posting(posting, residency_year, catalogue):
    """Recognize labels only: candidates are not requirement assignments or credit."""
    if posting["status"] != "posting":
        return {"status": "not_applicable", "reasons": [], "candidates": []}
    label = posting["value"]
    elective = bool(re.search(r"\(\s*elective\s*\)", label, re.IGNORECASE))
    remediation = bool(re.search(r"\bremediation\b", label, re.IGNORECASE))
    lookup = normalized_label(re.sub(r"\(\s*(?:elective|remediation)\s*\)", " ", label, flags=re.IGNORECASE))
    candidates = [dict(c, match_basis="exact") for c in catalogue
                  if normalized_label(c["label"]) == lookup
                  and (not elective or c["category"] == "elective")]
    years = recorded_years(residency_year)
    earlier_years = {f"r{year}" for year in range(1, max(int(y[1:]) for y in years))} if years else set()
    eligible_years = earlier_years if remediation else years
    eligible_context = "earlier_remediation_year" if remediation else "recorded_year"
    reasons = []
    if elective:
        reasons.append("explicit_elective")
    if remediation:
        reasons.append("remediation_credit_review")
    if not years:
        reasons.append("recorded_year_unknown")
    elif remediation and not eligible_years:
        reasons.append("no_earlier_year_context")
    for candidate in candidates:
        candidate_years = recorded_years(candidate["residency_year"])
        candidate["year_context"] = ("unknown" if not years or not candidate_years else
                                     eligible_context if eligible_years & candidate_years else "different_year")
    if not remediation and years and not any(c["year_context"] == "recorded_year" for c in candidates):
        eligible_context = "earlier_fallback_year"
        for candidate in candidates:
            if earlier_years & recorded_years(candidate["residency_year"]):
                candidate["year_context"] = eligible_context
    if any(not recorded_years(c["residency_year"]) for c in candidates):
        reasons.append("catalogue_year_unknown")
    if any(len(recorded_years(c["residency_year"])) > 1 for c in candidates):
        reasons.append("mixed_catalogue_years")
    # Keep every exact candidate; use all recorded years as one matching context.
    candidates.sort(key=lambda c: (c["category"] != "core", c["year_context"] != eligible_context))
    within_context = [c for c in candidates if c["year_context"] == eligible_context]
    preferred = [c for c in within_context if c["category"] == "core"] or within_context
    selected = (preferred[0] if years and len(preferred) == 1
                and "catalogue_year_unknown" not in reasons and "mixed_catalogue_years" not in reasons else None)
    if selected and eligible_context == "earlier_fallback_year":
        reasons.append("earlier_year_fallback")
    if len(years) > 1 and not selected:
        reasons.append("mixed_recorded_years")
    relevant = preferred if years and preferred else candidates
    if {c["category"] for c in relevant} == {"core", "elective"}:
        reasons.append("core_elective_ambiguity")
    if not selected and any(c["year_context"] == "different_year" for c in candidates):
        reasons.append("requirement_year_review")
    if not candidates:
        reasons.append("no_catalogue_match")
    elif len(candidates) > 1:
        reasons.append("catalogue_alternatives" if selected else "multiple_catalogue_candidates")
    status = ("matched" if selected else "unmatched" if not candidates else
              "ambiguous" if len(candidates) > 1 else "needs_review")
    return {"status": status, "reasons": reasons, "candidates": candidates, "selected_candidate": selected}


def intake_slot_id(record, year):
    """A vacancy number identifies a slot in one intake, never a person."""
    number = re.fullmatch(r"resident ([1-9][0-9]*)", normalized_label(record.get("name")))
    if (number and not normalized_label(record.get("mcr"))
            and normalized_label(record.get("residency_year")) == "r1"
            and (record.get("intake") or "").strip() == str(year)):
        return f"intake-{year}-slot-{int(number[1]):02d}"
    return None


def attach_intake_slots(result):
    """Identify workbook placeholders without creating additional residents."""
    summary = result.get("incoming_intake")
    if summary is not None:
        year = summary["year"]
        # Copy planning rows so slot metadata does not alter source history.
        result["residents"] = [dict(r, slot_id=slot) if (slot := intake_slot_id(r, year)) else r
                               for r in result["residents"]]
    return result


def review_import(result, yearly_sheets=None):
    """Link source records conservatively, retaining every raw value for review."""
    issues = []
    sheets = result.get("annual_sheets", yearly_sheets)
    annual = ([s["residents"] for s in sheets] if sheets is not None else
              [result["residents"]] + [s["residents"] for s in result["histories"]])
    identities = [r for rows in annual for r in rows] + result["requests"]
    mcrs = defaultdict(set)
    ambiguous_names = set()
    duplicate_sources = set()

    def key(record):
        return " ".join((record.get("mcr") or "").split()).upper()

    def name(record):
        return " ".join((record.get("name") or "").split()).casefold()

    def issue(code, title, message, records):
        issues.append({"code": code, "severity": "warning", "title": title, "message": message,
                       "source": records[0]["source"],
                       "records": [{"name": r.get("name"), "mcr": r.get("mcr"), "source": r["source"]}
                                   for r in records]})

    # Placeholders are local to one explicitly recorded intake, never identities
    # for linking history or requests. Missing/unclear intake remains unsafe.
    placeholder_sources = set()
    for sheet in sheets or []:
        placeholders = defaultdict(list)
        for record in sheet["residents"]:
            record["is_intake_placeholder"] = bool(
                not key(record) and normalized_label(record.get("residency_year")) == "r1"
                and (record.get("intake") or "").strip() == str(sheet["year"])
                and re.fullmatch(r"resident [1-9][0-9]*", name(record)))
            if record["is_intake_placeholder"]:
                placeholder_sources.add((record["source"]["sheet"], record["source"]["row"]))
                placeholders[name(record)].append(record)
        for repeated in placeholders.values():
            if len(repeated) > 1:
                issue("duplicate_intake_placeholder", "Duplicate intake placeholder",
                      "This placeholder number appears more than once in the same annual worksheet.", repeated)

    if result.get("months"):
        intake_year = int(result["months"][0]["month"][:4])
        cohort = []
        for record in result["residents"]:
            if normalized_label(record.get("residency_year")) != "r1":
                continue
            intake = (record.get("intake") or "").strip()
            if not re.fullmatch(r"[0-9]{4}", intake) or int(intake) > intake_year:
                issue("unclear_intake", "Incoming R1 intake needs review",
                      "Confirm one four-digit intake year no later than the planning year to determine whether this R1 row belongs to the planning intake.", [record])
            elif intake == str(intake_year):
                cohort.append(record)
        placeholder_count = sum(record.get("is_intake_placeholder", False) for record in cohort)
        result["incoming_intake"] = {
            "year": intake_year, "expected_size": 24, "total_count": len(cohort),
            "named_count": sum(bool(name(record)) and not record.get("is_intake_placeholder", False) for record in cohort),
            "placeholder_count": placeholder_count,
            "resident_sources": [record["source"] for record in cohort]}
        if len(cohort) > 24:
            issue("excess_intake", "Incoming R1 intake exceeds 24",
                  f"{len(cohort)} rows belong to the {intake_year} intake, including {placeholder_count} placeholders. Review duplicates or excess rows; none were removed.", cohort)

    for record in identities:
        mcr, resident_name = key(record), name(record)
        if not mcr and (record["source"]["sheet"], record["source"]["row"]) not in placeholder_sources:
            issue("missing_mcr", "Missing MCR", "This row cannot be matched by MCR.", [record])
        if not resident_name:
            issue("missing_name", "Missing resident name", "Confirm this row's identity in the workbook.", [record])
        if mcr and resident_name:
            mcrs[mcr].add(resident_name)
    for rows in annual:
        counts = defaultdict(list)
        for record in rows:
            if key(record):
                counts[key(record)].append(record)
        for mcr, repeated in counts.items():
            if len(repeated) > 1:
                for record in repeated:
                    duplicate_sources.add((record["source"]["sheet"], record["source"]["row"]))
                issue("duplicate_mcr", f"Duplicate MCR {mcr}",
                      "This MCR appears more than once in the same annual worksheet.", repeated)
    for mcr, recorded_names in mcrs.items():
        if len(recorded_names) > 1:
            issue("conflicting_identity", f"Different names for MCR {mcr}",
                  "The same MCR is recorded with different names.",
                  [r for r in identities if key(r) == mcr])
    # A name may acquire another MCR across years. Two records with that name
    # in one annual sheet cannot establish which identity owns earlier history.
    for rows in annual:
        named = defaultdict(list)
        for record in rows:
            if name(record):
                named[name(record)].append(record)
        for resident_name, repeated in named.items():
            if len(repeated) > 1 and len({key(r) for r in repeated}) > 1:
                ambiguous_names.add(resident_name)
    for resident_name in sorted(ambiguous_names):
        issue("conflicting_identity", "Multiple residents with the same name",
              "This name appears with different MCRs in the same annual worksheet.",
              [r for r in identities if name(r) == resident_name])

    target = defaultdict(list)
    target_names = defaultdict(list)
    for record in result["residents"]:
        if key(record):
            target[key(record)].append(record)
        if name(record) and key(record):
            target_names[name(record)].append(record)
    for record in [r for rows in annual for r in rows] + result["requests"]:
        mcr = key(record)
        candidates = (target[mcr] or target_names[name(record)]) if mcr else []
        ambiguous = (len(candidates) > 1 or name(record) in ambiguous_names
                     or len(mcrs[mcr]) > 1
                     or (record["source"]["sheet"], record["source"]["row"]) in duplicate_sources
                     or not name(record)
                     or any(not name(r) for r in candidates))
        matched = len(candidates) == 1 and not ambiguous
        record["match_status"] = "matched" if matched else "ambiguous" if ambiguous else "unmatched"
        record["matched_resident_source"] = candidates[0]["source"] if matched else None

    known_mcrs = {key(r) for rows in annual for r in rows if key(r)}
    for record in result["requests"]:
        if record["match_status"] == "unmatched" and key(record) and key(record) not in known_mcrs:
            issue("unmatched_request", "Request has no matching resident", "This request MCR was not found in any yearly resident tab.", [record])

    catalogue = posting_catalogue(result["postings"])
    for rows in annual:
        for record in rows:
            for posting in record["postings"]:
                posting["catalogue_match"] = match_posting(posting, record.get("residency_year"), catalogue)

    # Reference existence only; requirement year and credit are reviewed separately.
    unmapped = {}
    for rows in annual:
        for record in rows:
            for posting in record["postings"]:
                value = posting["value"]
                if posting["status"] == "posting" and not posting["catalogue_match"]["candidates"]:
                    ref = posting["source"]
                    unmapped[(value, ref["sheet"], ref["row"], ref.get("column"))] = ref
    if unmapped:
        issues.append({"code": "unmapped_posting", "severity": "info",
                       "title": "Posting labels without a catalogue reference",
                       "message": f"{len({entry[0] for entry in unmapped})} distinct posting values have no reference in the core or elective catalogue.",
                       "source": next(iter(unmapped.values())), "values": [entry[0] for entry in unmapped],
                       "sources": list(unmapped.values())})
    result["issues"] = issues
    return result


def parse_workbook(content: bytes, target_year: int = 2027) -> dict:
    if len(content) > MAX_UPLOAD_BYTES:
        raise WorkbookError("Workbook exceeds the 10 MB upload limit")
    try:
        with ZipFile(BytesIO(content)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_EXPANDED_BYTES:
                raise WorkbookError("Workbook expanded contents exceed 50 MB")
            if len(archive.infolist()) > 2000:
                raise WorkbookError("Workbook contains too many archive entries")
        workbook = load_workbook(BytesIO(content), data_only=True, keep_links=False)
    except WorkbookError:
        raise
    except Exception as exc:
        raise WorkbookError("Unable to read this XLSX workbook; upload a valid, unencrypted .xlsx file") from exc
    try:
        for sheet in workbook:
            if sheet.max_row > 10000 or sheet.max_column > 100:
                raise WorkbookError(f"{sheet.title}: worksheet exceeds supported dimensions (10000 rows, 100 columns)")
        years = sorted([yearly_sheet(s) for s in workbook if s.title.lower().startswith("jul")], key=lambda s: s["year"])
        if len({s["year"] for s in years}) != len(years):
            raise WorkbookError("Workbook contains ambiguous duplicate planning years")
        target = next((s for s in years if s["year"] == target_year), None)
        if target is None:
            raise WorkbookError(f"No July {target_year} - June {target_year + 1} worksheet found")
        for required in ("Request", "Postings"):
            if required not in workbook.sheetnames:
                raise WorkbookError(f"Required worksheet missing: {required}")
        request = workbook["Request"]
        request_row, request_columns = header(request, {"name", "mcr no.", "posting request", "period"})
        requests = records(request, request_row, request_columns,
                           {**IDENTITY_FIELDS, "posting_request": "posting request", "period": "period"})
        postings = workbook["Postings"]
        posting_row, posting_columns = header(postings, {"residency year", "core posting", "duration (months)", "max", "remarks"})
        core = records(postings, posting_row, posting_columns,
                       {"residency_year": "residency year", "posting": "core posting", "duration_months": "duration (months)", "max": "max", "remarks": "remarks"})
        rows = [{"source": source(postings, row[0].row),
                 "cells": {c.column_letter: text(c.value) for c in row if c.value is not None}}
                for row in postings if any(c.value is not None for c in row)]
        return attach_intake_slots(review_import({"target_year": target_year, "target_sheet": target["sheet"],
                "available_years": [{"year": s["year"], "sheet": s["sheet"]} for s in years],
                "months": target["months"], "residents": target["residents"],
                "histories": [s for s in years if s["year"] < target_year], "annual_sheets": years, "requests": requests,
                "postings": {"core": core, "electives": elective_catalogue(postings, posting_row, posting_columns), "rows": rows}, "warnings": []}, yearly_sheets=years))
    finally:
        workbook.close()

