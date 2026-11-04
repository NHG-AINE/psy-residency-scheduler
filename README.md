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

## R1 backend draft

After installing `backend/requirements.txt`, call the pure backend function:

```python
from backend.history_review import ReviewStore
from backend.r1_solver import draft_r1_schedule
from backend.workbook_import import parse_workbook

with open("posting-input.xlsx", "rb") as source:
    workbook = parse_workbook(source.read(), target_year=2027)
result = draft_r1_schedule(workbook, ReviewStore(version=1, decisions=[]), max_seconds=10)
```

This drafts only residents whose recorded years include R1, including mixed-year
residents with a supported R1 history. Other residents and months after R1
completion are explicitly outside scope. Upload values and review decisions are
unchanged; current postings may be rescheduled. Requests are not interpreted.

LOA pauses the training clock. Medicine and Neurology occupy the first six
training months, with one two-month Neurology block within its paired route;
Inpatient Psychiatry occupies the next six at one institution. Unfinished months
carry forward beyond June. Continuing residents need a complete, consistent
history from July of their recorded intake. Missing evidence, conflicting phase
history, or history already extending into R2 requires review. Unknown R1 posting
remarks also block the draft. Finite capacity shared with excluded residents
requires review; this draft does not validate a whole-programme timetable.

Soft priorities are incoming route distribution first, monthly Medicine-to-
Neurology ratio second. Targets are 12/9/3 for 24 active incoming residents and
12/9/2 for 23; other sizes use largest-remainder 12:9:3 shares. Full-horizon LOA
residents are excluded from that target cohort; monthly ratios use actual active
first-phase residents. These targets can relax under hard constraints, and the
result reports deviations. This ordering is an initial solver default.

Check `status`: only `optimal` and `feasible` contain a draft. `blocked` includes
sourced review findings; `infeasible`, `unknown` (including an expired time limit),
and `model_invalid` contain no assignments. A feasible result has not necessarily
reached the best soft targets. There is no solver API or interface yet.
