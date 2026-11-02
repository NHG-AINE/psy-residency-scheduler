# PSY Residency Scheduler

A posting planner for the NHG Psychiatry Residency Programme.

## Getting started

With Docker Desktop running, start both services from the repository root:

```sh
docker compose up --build
```

- Frontend: [http://localhost:5173](http://localhost:5173)
- Backend health: [http://localhost:8000/api/health](http://localhost:8000/api/health)

To stop both services, run this from another terminal in the repository root:

```sh
docker compose down
```

## Workbook import

Choose an `.xlsx` workbook in the app to review its timetable, residents,
requests, postings and import issues. See [Workbook import](docs/workbook-import.md)
for the expected format and current limits.

## Tech stack

| Area | Technology |
| --- | --- |
| Frontend | React + TypeScript + Vite |
| UI and styling | Radix Primitives + Tailwind CSS |
| Backend | Python + FastAPI |
| Scheduling engine | Google OR-Tools (CP-SAT) |
| Database, authentication and storage | Supabase |
| Frontend hosting | Vercel |
