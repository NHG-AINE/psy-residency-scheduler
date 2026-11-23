# Scheduler optimisation techniques

The scheduler uses one time budget to find a valid draft and improve it. Finishing
an early stage sooner gives the next preference more time. A two-minute run can
still take two minutes and return a better timetable.

For the scheduling rules and the order of preferences, see [constraints.md](constraints.md).

## Work out which months a block can start

If a resident starts in July and needs four uninterrupted three-month blocks, the
possible starts are July, October, January and April. The solver can skip August
because no preceding block could finish after just one month.

These dates come from the resident’s remaining training. A partially completed
block resumes first, and LOA pauses the count of training months. R2–R5 use this
calculation. R1 uses its own Medicine, Neurology and Inpatient Psychiatry routes.

See `add_blocks` in [r2_rules.py](../backend/rules/r2_rules.py).

## Find a valid draft first

The scheduler first finds a timetable that meets the hard constraints, including
LOA and posting duration. That timetable can still exceed a monthly capacity
target. The capacity stage then tries to reduce the excess.

Once the scheduler has a valid draft, it keeps the best one found so far. If a
later stage runs out of time, staff can still review that draft.

See `_solve_priorities` in [scheduler.py](../backend/scheduler.py).

## Add preferences as the solver needs them

Build each preference when its stage starts. For example, the capacity stage
counts places over max. It has no need yet to calculate how evenly residents
are spread across institutions or how many are posted alone.

When a stage proves its best score, the scheduler keeps that score for the rest
of the run. It can still move individual residents. For example, two residents
can swap sites if the swap preserves the earlier scores.

The app calculates the scores and request outcomes shown to staff from the
timetable it returns. A preference can therefore have a displayed score even if
the solver ran out of time before reaching its stage.

See `build_preferences` inside `draft_schedule` in [scheduler.py](../backend/scheduler.py).

## Prove a stage is optimal

A stage tracks the score of the best timetable found and a proven lower bound.
If the timetable scores 10 and the solver has proved that every valid timetable
scores at least 7, the optimum is somewhere from 7 to 10. If it finds a
timetable scoring 7, it can move on. It can also move on if it proves that 10 is
the lowest possible score.

For some stages, a smaller model drops restrictions to make the proof easier. A
timetable in that smaller model might be impossible to schedule in full. The
full solver uses only the lower bound the smaller model proves. If the smaller
search returns no usable bound, the full search continues.

| Stage | How the bound works |
| --- | --- |
| R1 Medicine and Neurology ratio | The smaller model keeps the proven R1 route-distribution score and considers the monthly Medicine and Neurology patterns. It can leave out unrelated choices, such as the inpatient destination. |
| R2 and R4 posting balance | With 10 residents across four posting types, the most even possible split is 3/3/2/2. Four pairs differ by one, so the monthly penalty is at least 4. In general, if `r = total % posting_types`, the minimum from the counts alone is `r × (posting_types − r)`. Other restrictions can raise it. |
| R5 posting balance | When the monthly R5 totals are fixed and each posting counts towards one requirement, a smaller model can compare weighted counts one month at a time. It leaves R5 out of this bound when routes can change those totals or a posting shares credit across requirements. The full timetable still scores R5 balance. |
| Stronger posting-balance bound | Where the routes allow it, a second calculation keeps block starts, progression and the proven request score. It simplifies institution choices only when the requests treat them alike. The scheduler skips this calculation for shared-credit or flexible R5 routes, including split electives. |
| Capacity overflow | For each requirement, compare unavoidable demand with the total places available over the planning year. If residents need at least 78 posting-months and the sites offer 72, at least 6 posting-months must exceed max. If an eligible site has no supplied max, this calculation claims no shortage for that requirement. It also leaves out optional R5 route demand. |

R3 has no separate posting-balance bound. For institution allocation, OR-Tools
calculates its own bounds during the full search.

See `ratio_relaxation` in [r1_rules.py](../backend/rules/r1_rules.py) and
`_posting_balance`, `_posting_balance_relaxation`, `_posting_block_relaxation`
and `_capacity_overflow_lower_bound` in [scheduler.py](../backend/scheduler.py).

## Group equivalent R1 choices

In the smaller R1 model, residents can be grouped when they have the same
Medicine and Neurology patterns and the same intake status. Suppose ten
residents have the same two choices. For the ratio calculation, it is enough to
know that six take the first pattern and four take the second. Swapping two
names gives the same counts.

The full scheduler still assigns each resident individually, with their own
history, availability and restrictions.

See `ratio_relaxation` in [r1_rules.py](../backend/rules/r1_rules.py).

## Count monthly postings once

For each month, the solver defines one count per posting type and links it to
the residents’ assignments. Suppose July has 6 Child, 6 Geriatric and 12 Elective.
Both the Child–Geriatric comparison and the Child–Elective comparison can use
the same July Child count.

If a resident’s assignment changes, the linked count changes with it. The
comparisons use the same weights as before. In R5, the counts also allow a
posting to contribute to two requirements.

See `_posting_count` and the posting-balance builder in [PR #35](https://github.com/NHG-AINE/psy-residency-scheduler/pull/35).

## Reuse a timetable and share the search work

Each stage receives the best timetable found so far as a starting suggestion.
The solver can change assignments while preserving scores already proved optimal.

OR-Tools chooses the number of workers automatically. The workers try different
search strategies on the same timetable, so they can account for mixed-year
residents and shared constraints. Even with the same workbook and random seed,
repeated runs can find different drafts before time runs out.

See `_solve_priorities` and `SOLVER_WORKERS` in [scheduler.py](../backend/scheduler.py).

## Measure whether a change helps

- Count the initial search, the time spent building each preference and any
  smaller-model searches within the selected limit. Workbook preparation,
  processing the result and solver shutdown can add to the elapsed time staff see.
- Compare repeated runs with the same workbook, review decisions, time limit and
  worker settings. Run them one at a time so they do not compete for the same machine.
- Record the returned score, the proven lower bound, time spent in the stage and
  the next stage reached. For example, if posting balance took 30 seconds instead
  of 60, check how much time was left when it started and whether it proved optimality.
- Check a new bound against small timetables whose optimum is known. The bound
  must never exceed that optimum. If the change only rewrites how a score is
  calculated, verify that the same assignments still give the same score.
- Keep a change when repeated runs show a benefit worth the added code. Record
  which workbook and settings produced the result.
