# Historical Posting Review

## Scope

History review matches the posting names in the workbook to the Postings catalogue.
It covers all annual sheets in the upload, whichever planning year is selected on the timetable.

Each entry keeps its original wording, recorded R-year, monthly status and source cells.
The requirements ledger handles training credit, completion and outstanding requirements.

## Automatic matching rules

Compare the full posting name, ignoring capitalisation and extra spaces. Treat `&` and
`and` as equivalent. Ignore `(North)`, `(South)`, `(East)` and `(West)` when comparing
names. For example, `IMH General Psychiatry (East)` matches `IMH General Psychiatry`.
In `IMH Adult Neurodevelopmental Disorders Service (ANDS)`, `(ANDS)` remains part of the name.

Read `(Elective)` and `(Remediation)` separately because they affect which postings are
eligible. Other wording differences or damaged text need an approved mapping. A partial
name match or an extra trailing `Psychiatry` is insufficient.

1. If the label includes `(Elective)`, consider only electives. Otherwise, keep both
   core and elective candidates.
2. Check all recorded R-years together. For `R2,R3`, an exact match in either year is
   in scope. If neither year has a match, check years below the highest recorded year.
   If the recorded years already have competing matches after applying the category
   preference below, send the entry for review.
3. For remediation, start with the earlier years directly. A resident recorded as
   `R2,R3` can match R1 or R2. A resident recorded only as R1 has no earlier year to check.
4. Within the eligible years, choose the sole core match if there is one. If there
   are no core matches, choose the sole elective match. Multiple eligible core
   matches still need review, even if there is only one elective.
5. Leave the entry for review if the recorded R-year is missing or if a matching
   catalogue entry has an unknown or mixed R-year. Never automatically select a
   posting above the highest recorded year. Keep the other exact candidates visible for review.

If the catalogue contains no elective entries, the matcher has no elective candidates.
The workbook still needs a `Postings` or `Posting` sheet.

## Review table and decisions

- Show the original posting, months, recorded R-year, source cells, catalogue
  candidates and reason for review.
- Group consecutive months when the resident's MCR, name, recorded R-year and original
  posting text agree. A posting can continue from June on one sheet to July on the next.
  A blank month, LOA or a change of label breaks the run. Where identity is uncertain,
  keep records from different workbook rows separate.
- **Needs review** shows unresolved labels and entries with invalid saved decisions.
  Once a label is matched, an unconfirmed requirement year alone does not keep it in this list.
- **All entries** also includes automatic matches, manually confirmed labels and recognised remediation.

Choose **This resident and these months** to confirm a posting for one resident and
period. You may also confirm the requirement year if it fits the catalogue entry.
The workbook's recorded R-year stays as entered.

Choose **Shared label mapping** to reuse a wording decision for the same original
label, recorded-year context and core or elective category. Each resident's requirement
year is assessed separately. An explicit `(Elective)` label must map to an elective
under either option. Store approved mappings as review data.

Identity issues appear in Issues and do not prevent label recognition. If the resident's
identity is uncertain, the editor still allows a shared mapping. Resolve the identity
issue before saving a resident-specific decision.

Valid saved decisions take precedence over automatic matches. Stale, conflicting or
unsafe decisions stay unapplied, with the reason visible for review. An automatic match
does not create a saved decision or confirm a requirement year. Recognised remediation
can count in the ledger under the usual identity, year, institution and duration rules.
It needs no separate remediation approval.

## Saving and reuploading

- Review decisions are saved in this browser for this site. Refreshing the page can
  restore the uploaded workbook and generated draft from the saved workbook session.
  Uploading a workbook again reapplies compatible review decisions.
- To back up decisions or move them to another browser, use **Export review JSON**
  and **Import review JSON**. Decisions do not sync between users. The JSON contains
  resident identifiers and posting history, so handle it like the workbook.
- A resident decision is tied to the MCR, original labels and calendar months. The
  app also checks the name and recorded R-year. Catalogue entries are identified
  by category, year and full label. The app checks their duration, capacity, remarks,
  allowed block lengths and credit rules. Moving an otherwise identical entry to
  another row or sheet preserves the match.
- For example, suppose you confirmed January–March and a later upload shows the
  posting continued through June. The app flags the changed period for review. It
  does not extend your decision to April–June. If the period is absent from an
  upload, the decision stays saved for a later one.
- The app checks the JSON version, fields and decision scopes before importing. If
  an imported decision conflicts with an existing one, the whole import is rejected.
  Remove the existing decision before importing its replacement, or use the inline
  editor to replace that decision directly.
- If saving fails, the editor stays open and existing decisions are preserved. If
  saved data is unreadable, saving stays blocked until you choose to start new review data.
