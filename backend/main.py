from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

if __package__:
    from .workbook_import import MAX_UPLOAD_BYTES, WorkbookError, parse_workbook
else:
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
