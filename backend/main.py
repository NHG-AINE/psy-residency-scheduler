from fastapi import FastAPI

app = FastAPI(title="PSY Residency Scheduler API")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
