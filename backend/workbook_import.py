"""Read posting records without interpreting them as completed training or rules."""
from datetime import date, datetime
from collections import defaultdict
from io import BytesIO
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
            resident["postings"].append({"month": month["month"], "value": text(cell.value),
                                          "source": source(sheet, cell.row, cell.column_letter)})
    return {"year": first.year, "sheet": sheet.title, "months": months, "residents": residents}


def review_import(result):
    """Link source records conservatively, retaining every raw value for review."""
    issues = []
    annual = [result["residents"]] + [s["residents"] for s in result["histories"]]
    identities = [r for rows in annual for r in rows] + result["requests"]
    names, mcrs = defaultdict(set), defaultdict(set)
    duplicate_sources = set()

    def key(record):
        return " ".join((record.get("mcr") or "").split()).upper()

    def name(record):
        return " ".join((record.get("name") or "").split()).casefold()

    def issue(code, message, record):
        issues.append({"code": code, "severity": "warning", "message": message,
                       "source": record["source"]})

    for record in identities:
        mcr, resident_name = key(record), name(record)
        if not mcr:
            issue("missing_mcr", "MCR is missing; this row cannot be matched by identity.", record)
        if not resident_name:
            issue("missing_name", "Resident name is missing; confirm this row's identity.", record)
        if mcr and resident_name:
            names[resident_name].add(mcr)
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
                    issue("duplicate_mcr", f"MCR {mcr} occurs more than once in this annual worksheet.", record)
    for record in identities:
        if len(names[name(record)]) > 1 or len(mcrs[key(record)]) > 1:
            issue("conflicting_identity", "Name and MCR disagree across source rows; matching is withheld until reviewed.", record)

    target = defaultdict(list)
    for record in result["residents"]:
        if key(record):
            target[key(record)].append(record)
    for record in [r for rows in annual[1:] for r in rows] + result["requests"]:
        mcr = key(record)
        candidates = target[mcr] if mcr else []
        ambiguous = (len(candidates) > 1 or len(names[name(record)]) > 1
                     or len(mcrs[mcr]) > 1
                     or (record["source"]["sheet"], record["source"]["row"]) in duplicate_sources
                     or not name(record)
                     or any(not name(r) for r in candidates))
        matched = len(candidates) == 1 and not ambiguous
        record["match_status"] = "matched" if matched else "ambiguous" if ambiguous else "unmatched"
        record["matched_resident_source"] = candidates[0]["source"] if matched else None

    for record in result["requests"]:
        if record["match_status"] == "unmatched" and key(record):
            issue("unmatched_request", "Request MCR has no matching resident in the target worksheet.", record)

    # Exact references only: elective fragments, LOA and SAF notes remain raw,
    # without guessing aliases or treating a historical entry as training credit.
    known = {r["posting"] for r in result["postings"]["core"] if r.get("posting")}
    unmapped = {}
    for rows in annual:
        for record in rows:
            for posting in record["postings"]:
                value = posting["value"]
                if value and value not in known:
                    unmapped.setdefault(value, posting["source"])
    if unmapped:
        issues.append({"code": "unmapped_posting", "severity": "info",
                       "message": f"{len(unmapped)} distinct posting values have no exact Core Posting reference. Values are retained for review; this does not mean they are invalid.",
                       "source": next(iter(unmapped.values())), "values": list(unmapped),
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
        return review_import({"target_year": target_year, "target_sheet": target["sheet"],
                "available_years": [{"year": s["year"], "sheet": s["sheet"]} for s in years],
                "months": target["months"], "residents": target["residents"],
                "histories": [s for s in years if s["year"] < target_year], "requests": requests,
                "postings": {"core": core, "rows": rows}, "warnings": []})
    finally:
        workbook.close()

