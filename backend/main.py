from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from typing import Literal
from threading import Event
from time import monotonic
from uuid import uuid4
from starlette.concurrency import run_in_threadpool

if __package__:
    from .scheduler import DraftCancelled, draft_schedule
    from .requirement_ledger import build_requirement_ledger
    from .history_review import ReviewStore, evaluate_review
    from .workbook_import import MAX_UPLOAD_BYTES, WorkbookError, parse_workbook
else:
    from scheduler import DraftCancelled, draft_schedule
    from requirement_ledger import build_requirement_ledger
    from history_review import ReviewStore, evaluate_review
    from workbook_import import MAX_UPLOAD_BYTES, WorkbookError, parse_workbook

app = FastAPI(title="PSY Residency Scheduler API")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/import")
async def import_workbook(file: UploadFile = File(...), target_year: int = Form(2027)) -> dict:
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
