# Scheduler optimisation techniques

- This guide explains how we reduce search work without changing scheduling policy.
- For hard rules and preference order, read [constraints.md](constraints.md).
- A faster early stage gives later stages more time; it may not shorten the total run.

## Consider only valid block starts

- Calculate possible starts from the lengths of the remaining blocks, rather than trying every month.
- Example: four continuous three-month blocks with no LOA can start in July, October, January and April.
- Partial history and LOA change those starts. They are calculated, not fixed calendar dates.
- Shared block construction serves R2-R5; R1 uses its own candidate paths.
- Code: `add_blocks` in [r2_rules.py](../backend/rules/r2_rules.py).

## Keep a valid draft first

- Find a timetable satisfying the hard constraints before optimising preferences.
- Keep it as a fallback if a later search times out. A valid draft is not necessarily well balanced.
- Example: a draft may exceed a soft capacity target while still respecting LOA and required posting durations.
- Code: `_solve_priorities` in [scheduler.py](../backend/scheduler.py).

## Add preference calculations only when needed

- Build the initial model with hard constraints, then add each preference's calculations when its stage starts.
- Example: capacity optimisation does not need to carry institution-allocation or singleton calculations yet.
- Earlier proven scores remain protected. Individual assignments can still move.
- Calculate displayed scores and request outcomes from the chosen assignments, even if their stage was not reached.
- Code: `build_preferences` inside `draft_schedule` in [scheduler.py](../backend/scheduler.py).

## Use lower bounds to prove when a stage is finished

- A lower bound means: no valid timetable can score below this number. Lower scores are better.
- Example: best timetable score 10, bound 7 means keep searching; score 7 and bound 7 means optimal.
- Sometimes a smaller, more permissive model can prove a useful bound faster. Transfer only its certified bound, not its assignments or best-found score.
- Discard unknown results safely. A bound can be correct but too weak to improve performance.
- Current custom bounds:
  - **R1 ratio:** a smaller model preserves the proven route-distribution score and drops unrelated restrictions.
  - **R2/R4 balance:** the most even integer split gives a minimum pairwise penalty. For 10 residents across four postings, 3/3/2/2 has penalty 4. Generally, with `r = total % posting_types`, the minimum is `r * (posting_types - r)`.
  - **R5 balance:** a weighted monthly-count model drops cross-month coupling. Combined cores omit the R5 part of this bound; the stronger block projection is disabled for combined or flexible split routes it cannot safely represent.
  - **Capacity across years:** minimum unavoidable demand minus generous total supplied capacity gives a conservative bound. Example: 78 required posting-months and 72 available posting-months force at least 6 excess posting-months. Unlimited alternatives and uncertain generated R5 demand are omitted conservatively.
- R3 has no separate posting-balance bound. Institution allocation has no custom reduced-model bound; OR-Tools still calculates its own search bounds.
- Code: `ratio_relaxation` in [r1_rules.py](../backend/rules/r1_rules.py); `_posting_balance`, `_posting_balance_relaxation`, `_posting_block_relaxation` and `_capacity_overflow_lower_bound` in [scheduler.py](../backend/scheduler.py).

## Group equivalent choices in the smaller R1 model

- Group residents only when their projected Medicine/Neurology options and intake status are identical.
- Example: count how many of ten equivalent residents choose each pattern, instead of exploring every exchange of names.
- This grouping belongs to the smaller bound model. The full scheduler still keeps residents and their individual restrictions separate.
- Code: `ratio_relaxation` in [r1_rules.py](../backend/rules/r1_rules.py).

## Define monthly posting counts once

- Define a count once, then reuse it in comparisons instead of repeating long assignment expressions.
- Example: define Child = 6, Geriatric = 6 and Elective = 12 once, then compare those counts with the existing weights.
- Keep an equality linking each count to its actual assignments. Count limits must be safe for every valid schedule, including combined R5 core contributions.
- This changes the representation, not the penalty or valid timetables. It does not remove equal-score alternatives.
- Implementation: `_posting_count` and the posting-balance builder in [PR #35](https://github.com/NHG-AINE/psy-residency-scheduler/pull/35).

## Reuse solutions and search with multiple workers

- Give the next stage the previous assignment as a hint. A hint is a starting suggestion, not a locked timetable.
- Automatic workers let OR-Tools try several search strategies on the shared model.
- This is not a separate solver for each R-year. Mixed-year residents and shared constraints remain in one model.
- Parallel search can vary between runs, even with the same workbook and random seed.
- Code: `_solve_priorities` and `SOLVER_WORKERS` in [scheduler.py](../backend/scheduler.py).

## Share the budget and measure improvements

- Initial feasibility, preference searches, smaller-model solves and deferred preference construction share one search budget.
- Smaller models have capped allowances within that budget; they do not receive extra time.
- Input preparation, result processing and solver shutdown can make total elapsed time exceed the configured search limit.
- Advance only after proving the current priority optimal; never trade away an earlier proven score for a later preference.
- Compare repeated before/after runs using the same workbook, review decisions, search limit and worker settings. Avoid running benchmarks concurrently.
- Record returned draft scores, proof bounds, stage times and which later stages were reached. A shorter timed-out stage alone is not evidence of improvement.
- Test that reduced-model bounds never exceed small full-model optima and that equivalent formulations preserve scores.
- Keep an optimisation only when evidence justifies its complexity. Benchmark timings are observations, not guarantees for future workbooks.
