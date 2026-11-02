# Commit Style

Use Conventional Commits for all commit messages.

## Format

```text
<type>[optional scope][!]: <description>
```

- Keep the complete subject line within 72 characters.
- Put optional scopes in parentheses, such as `feat(import):`.
- Add `!` before the colon for breaking changes.

## Types

| Type | Use for |
| --- | --- |
| feat | New user-facing or domain behaviour |
| fix | Bug fixes and correctness repairs |
| refactor | Code restructuring without a behaviour change |
| perf | Performance improvements |
| test | Test-only changes |
| docs | Documentation-only changes |
| build | Build system or dependency changes |
| ci | Continuous integration configuration or scripts |
| deploy | Hosting, deployment or environment-routing configuration |
| chore | Maintenance that fits no more specific type |
| revert | Reverting an earlier change |

## Choosing a type

- Inspect the staged diff and choose its primary intent.
- Supporting tests or documentation do not change a feature or fix
  into a `test` or `docs` commit.
- Split unrelated changes into separate commits instead of using
  a vague umbrella type.

## Merge and history

- When merging main into a task branch, name the merge commit:
  `chore: merge latest main into <branch-name>`.
  Example: `chore: merge latest main into feature/workbook-import`.
- This applies when a merge commit is created. A fast-forward update
  creates no merge commit to name.
- Give pull requests into main a Conventional Commit title that follows
  this guide, including the 72-character subject limit.
- Prefer Rebase and merge for PRs with clean, focused commits. This keeps
  main linear while preserving the individual commits.
- Use Squash and merge for PRs with messy history, such as WIP or fixup
  commits, to combine them into one meaningful commit.
- Rebase merges retain individual commit messages; the PR title does not
  become an additional commit.
- For squash merges or an explicitly chosen merge commit, use the PR title
  as the commit subject instead of `Merge pull request #... from ...`.

## Examples

```text
feat(import): add workbook selection
fix(scheduler): exclude LOA months from allocation
docs: add scheduling constraints guide
feat(api)!: change schedule response format
```
