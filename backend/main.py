import json
from urllib.parse import quote
from fastapi.responses import JSONResponse, Response
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from typing import Annotated, Literal
from threading import Event
from time import monotonic
from uuid import uuid4
from starlette.concurrency import run_in_threadpool

if __package__:
    from .workbook_export import export_workbook
    from .scheduler import DraftCancelled, draft_schedule
    from .draft_edits import validate_draft_change
    from .requirement_ledger import build_requirement_ledger
    from .history_review import ReviewStore, evaluate_review
    from .workbook_import import MAX_UPLOAD_BYTES, WorkbookError, parse_workbook, prepare_year
else:
    from workbook_export import export_workbook
    from scheduler import DraftCancelled, draft_schedule
    from draft_edits import validate_draft_change
    from requirement_ledger import build_requirement_ledger
    from history_review import ReviewStore, evaluate_review
    from workbook_import import MAX_UPLOAD_BYTES, WorkbookError, parse_workbook, prepare_year

app = FastAPI(title="PSY Residency Scheduler API")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/import")
async def import_workbook(file: UploadFile = File(...), target_year: int | None = Form(None)) -> dict:
    try:
        if not file.filename or not file.filename.lower().endswith(".xlsx"):
            raise HTTPException(400, "Choose an .xlsx workbook")
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Workbook exceeds the 10 MB upload limit")
        try:
            return await run_in_threadpool(parse_workbook, content, target_year)
        except WorkbookError as exc:
            raise HTTPException(400, str(exc)) from exc
    finally:
        await file.close()


class HistoryReviewRequest(BaseModel):
    workbook: dict
    store: ReviewStore
    scope: Literal["history", "timetable"] = "history"


class PrepareYearRequest(BaseModel):
    target_year: int
    annual_sheets: list[dict]
    requests: list[dict]
    postings: dict
    store: ReviewStore


def prepare_year_with_labels(request: PrepareYearRequest):
    workbook = prepare_year(request.annual_sheets, request.requests, request.postings, request.target_year)
    return JSONResponse({"workbook": workbook, "labels": evaluate_review(workbook, request.store, "timetable")})


@app.post("/api/prepare-year")
async def prepare_planning_year(request: PrepareYearRequest):
    try:
        return await run_in_threadpool(prepare_year_with_labels, request)
    except WorkbookError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(422, "The workbook data is incomplete. Import the workbook again.") from exc


@app.post("/api/history-review")
async def history_review(request: HistoryReviewRequest):
    try:
        return await run_in_threadpool(evaluate_review, request.workbook, request.store, request.scope)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(422, "The workbook review data is incomplete. Import the workbook again.") from exc


class RequirementLedgerRequest(BaseModel):
    workbook: dict
    store: ReviewStore


@app.post("/api/requirement-ledger")
async def requirement_ledger(request: RequirementLedgerRequest):
    try:
        return await run_in_threadpool(build_requirement_ledger, request.workbook, request.store)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(422, "The workbook or planning period is incomplete. Import the workbook again for the selected planning year.") from exc


# ponytail: process-local operations; shared storage is needed if multiple backend workers are deployed.
DRAFT_REGISTRATION_TTL_SECONDS = 180
_draft_operations = {}


@app.post("/api/draft/start")
async def start_draft():
    now = monotonic()
    for token, operation in list(_draft_operations.items()):
        if not operation["running"] and now - operation["created"] > DRAFT_REGISTRATION_TTL_SECONDS:
            del _draft_operations[token]
    token = uuid4().hex
    _draft_operations[token] = {"cancel": Event(), "running": False, "created": now}
    return {"token": token}


@app.delete("/api/draft/{token}")
async def cancel_draft(token: str):
    operation = _draft_operations.get(token)
    if operation:
        operation["cancel"].set()
        if not operation["running"]:
            del _draft_operations[token]
    return {"cancelled": True}


class DraftRequest(RequirementLedgerRequest):
    max_seconds: Literal[60, 120, 300, 600] = 120


class DraftBlockChange(BaseModel):
    resident: dict
    start: str = Field(pattern=r"^\d{4}-\d{2}$")


class DraftEdit(DraftBlockChange):
    kind: Literal["edit"]
    posting: str = Field(min_length=1)
    institution: str = Field(min_length=1)
    offering: dict | None = None


class DraftSwap(DraftBlockChange):
    kind: Literal["swap"]
    destination: str = Field(pattern=r"^\d{4}-\d{2}$")


class DraftChangeRequest(RequirementLedgerRequest):
    draft: dict
    change: Annotated[DraftEdit | DraftSwap, Field(discriminator="kind")]


@app.post("/api/draft/validate-change")
async def validate_change(request: DraftChangeRequest):
    try:
        if request.workbook["target_year"] != max(item["year"] for item in request.workbook["available_years"]):
            raise ValueError("Edit postings in the latest planning year of this workbook.")
        return await run_in_threadpool(validate_draft_change, request.workbook, request.store, request.draft, request.change.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "The draft inputs are incomplete. Generate a new draft and retry.") from exc


@app.post("/api/draft")
async def generate_draft(request: DraftRequest, token: str | None = None):
    operation = _draft_operations.get(token) if token else None
    if token and (not operation or operation["running"]):
        raise HTTPException(409, "Draft operation is no longer available.")
    if operation:
        operation["running"] = True
    try:
        latest_year = max(item["year"] for item in request.workbook["available_years"])
        if request.workbook["target_year"] != latest_year:
            raise HTTPException(422, "Draft generation is available only for the latest planning year in this workbook.")
        if operation:
            result = await run_in_threadpool(draft_schedule, request.workbook, request.store, max_seconds=request.max_seconds, cancel=operation["cancel"])
            if operation["cancel"].is_set():
                raise DraftCancelled()
            return result
        return await run_in_threadpool(draft_schedule, request.workbook, request.store, max_seconds=request.max_seconds)
    except DraftCancelled as exc:
        raise HTTPException(409, "Draft generation cancelled.") from exc
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(422, "The draft inputs are incomplete. Re-import the workbook and review saved decisions.") from exc
    finally:
        if token:
            _draft_operations.pop(token, None)


@app.post("/api/export")
async def export_draft(originalFile: UploadFile = File(...), target_year: int = Form(...), draft: str = Form(...)):
    try:
        if not originalFile.filename or not originalFile.filename.lower().endswith(".xlsx"):
            raise HTTPException(400, "Choose an .xlsx workbook")
        content = await originalFile.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Workbook exceeds the 10 MB upload limit")
        try:
            data = json.loads(draft)
            output, retained = await run_in_threadpool(export_workbook, content, target_year, data)
        except (WorkbookError, KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
            raise HTTPException(422, str(exc) if isinstance(exc, WorkbookError) else "The draft export data is incomplete. Generate a new draft and retry.") from exc
        basename = originalFile.filename.replace("\\", "/").split("/")[-1][:-5]
        filename = f"{basename} - Draft {target_year}-{target_year + 1}.xlsx"
        return Response(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename),
                                 "X-Export-Retained-Residents": json.dumps(retained, ensure_ascii=True)})
    finally:
        await originalFile.close()
