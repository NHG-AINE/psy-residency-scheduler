# Workbook import

With the app running, choose or drop one `.xlsx` workbook (up to 10 MiB).
Import starts automatically. The planning year defaults to 2027 (July 2027
through June 2028); use **Planning year** to select another available year.

Review **Timetable**, **Residents**, **Requests**, **Postings** and **Issues**.
Search residents by name or MCR and expand a resident to inspect their details,
linked requests and earlier posting history. Sheet, row and cell references
help trace imported values back to the workbook. Check errors and warnings
before relying on the records; an invalid replacement keeps the previous import.

## Workbook conventions

- Year sheets need resident headers and twelve dated month headings, July
  through June. Month headings determine the timeline; detailed date ranges
  are retained for future display.
- Earlier year tabs provide history. Residents are linked by MCR only;
  missing or ambiguous identities produce warnings without guessing from names.
  History for residents absent from the selected year stays unlinked.
- `Postings` and `Request` sheets are read as source records. Their original
  text is retained rather than interpreted as scheduling rules.

Imported postings do not automatically count as completed training. This is a
review-only import: data remains in the current browser session and refreshing
clears it. Supabase persistence, scheduling and workbook export are not yet
connected.

## Backend checks

From the repository root in PowerShell, with a backend virtual environment:

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
backend/.venv/Scripts/python -m unittest discover -s backend -v
```

The Docker getting-started command rebuilds the services with their dependencies.
