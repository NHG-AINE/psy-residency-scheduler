# PSY Residency Scheduler

A posting planner for the NHG Psychiatry Residency Programme.

## Tech stack

| Area | Technology |
| --- | --- |
| Frontend | React + TypeScript + Vite |
| UI and styling | Radix Primitives + Tailwind CSS |
| Backend | Python + FastAPI |
| Scheduling engine | Google OR-Tools (CP-SAT) |
| Database, authentication and storage | Supabase |
| Frontend hosting | Vercel |

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
