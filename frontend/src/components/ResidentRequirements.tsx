import { useEffect, useState } from 'react'
import Skeleton from './Skeleton'
import { monthLabel, sameSource, sourceLabel } from '../lib/workbook'
import type { Resident, Workbook } from '../lib/workbook'
import { readReviewStore, reasonLabel, STORAGE_KEY } from '../lib/history-review'
import { evaluateRequirements, visibleRequirements } from '../lib/requirement-ledger'
import type { LedgerMonth, RequirementLedger, ResidentLedger, RequirementFilter, HistoricalNote } from '../lib/requirement-ledger'

const explanation: Record<string, string> = {
  unsafe_identity: 'Resident identity needs review in Issues. No history has been allocated.',
  unsafe_historical_identity_evidence_excluded: 'Some historical identity records are unsafe and have been excluded. Review Issues.',
  requirement_year_unconfirmed: 'The label is recognized, but its requirement year needs resident-specific confirmation.',
  conflicting_month_evidence: 'Conflicting records for the same month; no months allocated.',
  unresolved_history: 'The posting label or its allocation is unresolved.',
}
const explain = (reason: string) => explanation[reason] || reasonLabel(reason)
const dateLabel = (month: string) => new Date(`${month}-01T00:00:00Z`).toLocaleDateString('en-SG', { month: 'short', year: 'numeric', timeZone: 'UTC' })

function Evidence({ months }: { months: LedgerMonth[] }) {
  return <ul className="requirement-evidence">{months.map((month) => <li key={month.month}>
    <strong>{monthLabel(month.month)}</strong>{month.target && <span>{month.target.label}</span>}
    {month.reasons.length > 0 && <p>{month.reasons.map(explain).join(' ')}</p>}
    {month.evidence.map((evidence, index) => <div key={index}>{evidence.value || 'No entry'}<small>{evidence.recorded_year || 'R-year not recorded'} - {sourceLabel(evidence.source)}</small></div>)}
  </li>)}</ul>
}


export function HistoricalNotes({ notes = [] }: { notes?: HistoricalNote[] }) {
  if (!notes.length) return null
  return <details className="historical-notes">
    <summary><svg viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="7.25" /><path d="M10 9v4M10 6.5v.5" /></svg><span>Historical notes &middot; {notes.length}</span><span className="historical-notes-chevron" aria-hidden="true" /></summary>
    <div className="historical-notes-content">{notes.map((note) => <article className="historical-note" key={`${note.code}-${note.start}-${note.posting}`}>
      <h4>Historical warning</h4>
      <p>Inpatient Psychiatry was recorded before the required R1 Medicine and Neurology months were complete.</p>
      <p className="historical-note-period">{note.posting} &middot; {dateLabel(note.start)}{note.end !== note.start && ` \u2013 ${dateLabel(note.end)}`} &middot; {note.months} {note.months === 1 ? 'month' : 'months'}{Array.from(new Map(note.sources.map((source) => [JSON.stringify([source.sheet, source.row]), source])).values()).map((source) => <span className="historical-note-source" key={JSON.stringify([source.sheet, source.row])}> &middot; {source.sheet} &middot; row {source.row}</span>)}</p>
    </article>)}</div>
  </details>
}

export function RequirementContent({ ledger, cutoff, planningStart, onHistoryReview }: { ledger: ResidentLedger; cutoff: string; planningStart: string; onHistoryReview: () => void }) {
  const [filter, setFilter] = useState<RequirementFilter>('all')
  const requirements = visibleRequirements(ledger, filter)
  const completedRoute = ledger.r1_routes.find((route) => route.evidence_status === 'supported')
  const commonIds = ledger.r1_routes[0]?.requirement_ids.filter((id) => ledger.r1_routes.every((route) => route.requirement_ids.includes(id))) || []
  const pending = ledger.months.filter((month) => month.status === 'pending')
  const planningYear = Number(planningStart.slice(0, 4))
  return <section className="resident-requirements" aria-label="Requirements">
    <div className="requirements-toolbar"><h3>Months through {dateLabel(cutoff)} - Planning {planningYear}/{String(planningYear + 1).slice(-2)}</h3>
      <label>Show requirements<select value={filter} onChange={(event) => setFilter(event.target.value as RequirementFilter)}><option value="all">All</option><option value="completed">Completed</option><option value="missing">Missing</option></select></label>
    </div>
    <HistoricalNotes key={JSON.stringify(ledger.source)} notes={ledger.historical_notes} />
    {ledger.warnings.map((warning) => <p className="record-note" key={warning}>{explain(warning)}</p>)}
    {!ledger.identity_safe ? <p className="empty-note">Requirements cannot be allocated safely until identity issues are resolved.</p> : <>
      {!ledger.months.length && <p className="muted">No safely matched history before this planning period.</p>}
      <div className="table-scroll requirements-table"><table><caption className="sr-only">Scheduled requirement progress through the cutoff, in months</caption>
        <thead><tr><th scope="col">R-year</th><th scope="col">Requirement</th><th scope="col">Required</th><th scope="col">Counted</th><th scope="col">Remaining</th></tr></thead>
        <tbody>{requirements.map((requirement) => <tr key={requirement.requirement_id} className={requirement.evidence_status !== 'supported' ? 'requirement-missing' : undefined}>
          <td>{requirement.requirement_year}</td><th scope="row">{requirement.posting}
            {!completedRoute && requirement.requirement_year === 'R1' && !commonIds.includes(requirement.requirement_id) && <small>{requirement.requirement_id === 'r1.medicine_neurology' ? 'Alternative: combined route' : 'Alternative: separate route'}</small>}
          </th><td>{requirement.required_months}</td><td>{requirement.expected_months}</td><td>{requirement.remaining_months}</td>
        </tr>)}{!requirements.length && <tr><td colSpan={5}>No {filter === 'all' ? '' : filter + ' '}requirements to show.</td></tr>}</tbody>
      </table></div>
      {pending.length > 0 && <div className="requirements-pending"><h4>Pending records ({pending.length} months)</h4><button type="button" className="button button-secondary" onClick={onHistoryReview}>Open History review</button><details className="requirement-detail"><summary>Show pending records</summary><Evidence months={pending} /></details></div>}
    </>}
  </section>
}

export default function ResidentRequirements({ resident, workbook, onHistoryReview }: { resident: Resident; workbook: Workbook; onHistoryReview: () => void }) {
  const [attempt, setAttempt] = useState(0)
  const [loaded, setLoaded] = useState<{ workbook: Workbook; attempt: number; data: RequirementLedger } | null>(null)
  const [failure, setFailure] = useState<{ workbook: Workbook; attempt: number; message: string } | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    const changed = (event: StorageEvent) => { if (event.key === STORAGE_KEY || event.key === null) setAttempt((value) => value + 1) }
    window.addEventListener('storage', changed)
    void (async () => {
      try {
        const saved = readReviewStore(window.localStorage)
        if (saved.error) throw new Error(saved.error)
        const data = await evaluateRequirements(workbook, saved.store, controller.signal)
        if (!controller.signal.aborted) setLoaded({ workbook, attempt, data })
      } catch (problem) {
        if (!controller.signal.aborted) setFailure({ workbook, attempt, message: problem instanceof Error ? problem.message : 'Requirements could not be loaded.' })
      }
    })()
    return () => { controller.abort(); window.removeEventListener('storage', changed) }
  }, [workbook, attempt])
  const data = loaded?.workbook === workbook && loaded.attempt === attempt ? loaded.data : null
  const error = failure?.workbook === workbook && failure.attempt === attempt ? failure.message : ''
  const selected = data?.residents.find((person) => sameSource(person.source, resident.source))
  return <div aria-busy={!data && !error}>
    {error ? <div role="alert"><p>{error}</p><button type="button" className="button button-secondary" onClick={() => setAttempt((value) => value + 1)}>Retry requirements</button></div>
      : !data ? <><span role="status" className="sr-only">Loading requirements</span><Skeleton variant="requirements" /></>
      : selected ? <RequirementContent ledger={selected} cutoff={data.cutoff} planningStart={data.planning_start} onHistoryReview={onHistoryReview} />
      : <p className="empty-note">This resident is not present in the selected planning-year ledger. Re-import the workbook.</p>}
  </div>
}
