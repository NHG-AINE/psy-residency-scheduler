from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from typing import Literal
from starlette.concurrency import run_in_threadpool

if __package__:
    from .intake_links import IntakeLinkStore, apply_intake_links
    from .requirement_ledger import build_requirement_ledger
    from .history_review import ReviewStore, evaluate_review
    from .workbook_import import MAX_UPLOAD_BYTES, WorkbookError, parse_workbook
else:
    from intake_links import IntakeLinkStore, apply_intake_links
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


class IntakeLinksRequest(BaseModel):
    workbook: dict
    store: IntakeLinkStore


@app.post("/api/intake-links")
async def intake_links(request: IntakeLinksRequest):
    try:
        return await run_in_threadpool(apply_intake_links, request.workbook, request.store)
    except (KeyError, StopIteration, TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(422, "The intake data is incomplete. Re-import the workbook before reviewing links.") from exc
