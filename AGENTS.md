# AGENTS.md

PSY Residency Scheduler is a posting planner for the NHG Psychiatry Residency Programme.

## Working rules

- Read relevant code and documentation before coding. Do not guess intended behaviour.
- Clarify uncertain requirements and surface material tradeoffs before implementation.
- Write the minimum code needed. Reuse existing tools and components.
- Make focused changes. Avoid unrelated edits and unnecessary abstractions.
- If the user asks only for a plan, explanation or review, deliver that and stop there.
- Keep backend logic separate from the interface.
- Preserve historical data and export changes to a new workbook.
- Never commit credentials.

## Project guidance

- Follow the tech stack in README.md.
- Follow DESIGN.md when changing the interface.
- Read .agents/context/COMMIT_STYLE.md when proposing or writing commit messages.
- Read docs/programme-structure.md for R1-R5 postings, institutions and durations.
- Read docs/constraints.md to understand the hard and soft scheduling rules,
  posting interpretation and resident progression when reviewing, planning or
  implementing scheduling work.
- Read docs/cross-cluster.md to understand institution-to-cluster mappings,
  cross-cluster credit and exposure requirements when reviewing, planning or
  implementing scheduling work.
- Read [docs/scheduler-optimisation.md](docs/scheduler-optimisation.md) to understand
  search techniques and validation when reviewing or changing scheduler performance.
- Keep constraint documents focused on scheduling rules, not temporary
  implementation-status notes. Check the code to determine current support.

## Task planning and implementation

Start each task with a short plan. For a question or investigation, say what
you'll check. For any task that changes the repository, include:

- Scope: what will change and why.
- Branch: which branch you'll use.
- Commits: the proposed commit messages and what belongs in each.
- Verification: which existing checks cover the change and which important
  behaviours, edge cases or regressions need a new test.

When implementation is requested, delegate the agreed scope to one worker
unless the user asks you to implement directly. Use the model and reasoning
effort the user specifies. Otherwise, choose an available coding model suited
to the task, preferring a faster model for routine implementation when model
selection is supported. If delegation is unavailable, implement directly.

The main agent owns the result. Review the worker's diff against the plan,
simplify unnecessary code, check that existing features still work and run the
high-value checks identified in the plan.

## Testing

- Add high-value tests that protect important behaviour, edge cases
  or known regressions.
- Avoid tests that merely repeat the implementation or check trivial details.
- Run relevant checks and report results or limitations.

## Repository workflow

- Use a dedicated branch for repository changes. Continue on the current branch
  when the user asks or the work belongs to the same approved change.
- Name branches `<type>/<short-kebab-case-description>`.
  Use feature/, fix/, build/, ci/, docs/, refactor/, test/ or chore/.
  Example: `feature/workbook-import`.
- Commit and push only when explicitly asked.
