# Historical Posting Review

## Scope

- Recognize catalogue posting labels, not completed training requirements.
- Preserve original labels, recorded R-years, monthly statuses and workbook sources.
- Do not calculate duration credit, completion, progression or outstanding requirements.

## Automatic matching rules

- Match exact names, ignoring capitalization and extra spaces; handle `(Elective)` and `(Remediation)` separately from the name.
- Check all recorded R-years together: `R2,R3` considers both years.
- With `(Elective)`, consider electives only, regardless of capitalization.
- Otherwise, prefer a unique core candidate; if none exists, allow a unique elective candidate.
- If no exact candidate qualifies in the recorded years, check earlier years below the highest recorded R-year. Never use this fallback to bypass ambiguity in the recorded years.
- For remediation, check earlier years directly. `R2,R3` includes R1 and R2; R1 has no earlier year. Apply the same elective-marker and core-precedence rules.
- Select only one eligible candidate. Multiple remaining candidates, missing recorded years, or unknown/mixed catalogue years require review. Never automatically select a higher-year posting.
- Keep other catalogue candidates available as alternatives.
- Identity issues alone do not block label recognition; they remain in import Issues.
- Respect valid saved decisions. Stale, conflicting or unsafe resident-specific decisions remain unapplied and need review.
- Different wording or damaged text requires an approved mapping. No substring or optional trailing “Psychiatry” matching is implemented.
- Store approved mappings as review data, not in this document or application code.
- A missing optional elective catalogue provides no elective candidates but does not fail import.

## Review table and decisions

- Show original labels, months, recorded years, candidates and review reasons.
- Group consecutive months only when MCR, identity, label and recorded-year context agree, including across tabs. Keep unsafe identities and separated periods apart; exclude LOA and blanks.
- **Needs review:** unresolved labels and invalid saved decisions only.
- **All entries:** also show automatic and manually confirmed labels, including open requirement years and recognised remediation.
- A valid label match leaves Needs review even if its requirement year has not been manually confirmed.
- Automatic matching does not save a decision, assign a requirement year or award credit.
- **Resident decision:** confirms a label for that resident and those months. Requirement year is optional, separate and must fit the catalogue entry; it never changes the recorded R-year.
- **Shared mapping:** applies to the original label, recorded-year context and core/elective category. It confirms wording only, not other residents’ requirement years.
- An explicit elective marker requires an elective target for manual decisions too.
- Identity conflicts block resident-specific decisions and editor actions, but not shared wording mappings. Invalid saved resident decisions retain a visible reason.
- Recognised remediation can count in the requirements ledger under the usual identity, requirement-year, institution and duration rules. There is no separate remediation credit approval step; label recognition alone does not establish completion.

## Saving and reuploading

- Save decisions in localStorage for the current browser and site. There is no server storage or shared-user synchronization.
- Refreshing clears the uploaded workbook, not saved decisions. Reuploading reapplies compatible decisions; workbooks are not stored.
- Export/import review JSON for backup or transfer. It contains resident identifiers and history, so handle it like the workbook.
- Identify resident decisions by normalized MCR, exact labels and calendar months; check name and recorded-year context separately.
- Identify catalogue targets by category, year and full label; also check relevant notes, duration and limits. Row positions are not identifiers, so reordering rows or moving sheets preserves compatible decisions.
- Changed context/catalogue content, missing targets and conflicts need review. Absent periods stay saved for later imports. Existing decisions made for a shorter cutoff-period may overlap a newly combined full run; keep them unapplied with a changed-period reason until reviewed. Never broaden them automatically.
- Validate JSON version, fields and scopes before saving. Conflicting scopes reject the whole import; remove the existing decision before importing its replacement. The inline editor can replace its own scope.
- Storage failures preserve previous decisions and keep the editor open. Unreadable saved data blocks saving until the user explicitly starts new review data.
