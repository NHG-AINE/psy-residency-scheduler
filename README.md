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

## Tech stack

| Area | Technology |
| --- | --- |
| Frontend | React + TypeScript + Vite |
| UI and styling | Radix Primitives + Tailwind CSS |
| Backend | Python + FastAPI |
| Scheduling engine | Google OR-Tools (CP-SAT) |
| Database, authentication and storage | Supabase |
| Frontend hosting | Vercel |

Incoming R1 vacancies are filled to 24 when intake and identity checks are clear.
In **Residents > Incoming R1**, explicitly link a named resident to their placeholder.
Links and compatible slot postings are saved in this browser and restored on workbook
re-upload. Export/import intake-link JSON for a backup or another browser. Changed
identities and conflicting postings remain unapplied until reviewed; removing a link
restores the imported roster. Original annual workbook records are unchanged.
