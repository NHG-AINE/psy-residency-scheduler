# AGENTS.md

PSY Residency Scheduler is a posting planner for the NHG Psychiatry Residency Programme.

## Working rules

- Read relevant code and documentation before coding. Do not guess intended behaviour.
- Clarify uncertain requirements and surface material tradeoffs before implementation.
- Write the minimum code needed. Reuse existing tools and components.
- Make focused changes. Avoid unrelated edits and unnecessary abstractions.
- Do not spawn subagents unless explicitly requested.
- Keep backend logic separate from the interface.
- Preserve historical data and export changes to a new workbook.
- Never commit credentials.

## Project guidance

- Follow the tech stack in README.md.
- Follow DESIGN.md when changing the interface.
- Read .agents/context/COMMIT_STYLE.md when proposing or writing commit messages.
- Read docs/constraints.md when changing scheduling logic.
- Keep confirmed requirements distinct from implemented constraints.

## Implementation plans

Before implementing a feature, provide a short, readable plan covering:

- Scope: what will be added or changed.
- Branch: the proposed branch name.
- Commits: intended commit messages and what each includes.
- Tests: which checks will verify the feature.

## Testing

- Add high-value tests that protect important behaviour, edge cases
  or known regressions.
- Avoid tests that merely repeat the implementation or check trivial details.
- Run relevant checks and report results or limitations.

## Repository workflow

- Start each new task on a dedicated branch before making changes.
- Name branches `<type>/<short-kebab-case-description>`.
  Use feature/, fix/, build/, ci/, docs/, refactor/, test/ or chore/.
  Example: `feature/workbook-import`.
- Commit and push only when explicitly asked.
