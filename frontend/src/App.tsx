import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { exportDraft, downloadDraft } from './lib/draft-export'
import { restoreSession, saveSession } from './lib/workbook-session'
import { useDraftSchedule } from './lib/use-draft-schedule'
import type { DraftState } from './lib/use-draft-schedule'
import RequestDetails from './components/RequestDetails'
import RequestOutcomeFilter from './components/RequestOutcomeFilter'
import type { DraftSchedule, RequestStatus } from './lib/draft-schedule'
import { draftBlockerLabel, draftPostings, draftResidentYear, groupDraftResidents, requestSummary, filterRequestResidents } from './lib/draft-schedule'
import Skeleton from './components/Skeleton'
import DraftTimer from './components/DraftTimer'
import DraftActions from './components/DraftActions'
import MonthlyBreakdown from './components/MonthlyBreakdown'
import ScrollToTop from './components/ScrollToTop'
import { scrollToPosition } from './lib/scroll'
import ResidentRequirements from './components/ResidentRequirements'
import ImportIssues from './components/ImportIssues'
import PostingReference from './components/PostingReference'
import HistoricalPostingReview from './components/HistoricalPostingReview'
import SearchField from './components/SearchField'
import TimetableGrid from './components/TimetableGrid'
import { importWorkbook, monthLabel, sameSource, sourceLabel, workbookError } from './lib/workbook'
import type { Resident, Source, Workbook } from './lib/workbook'
import { groupPostings, postingCategory, postingDisplay } from './lib/posting-blocks'
import { evaluateHistory, readReviewStore, STORAGE_KEY } from './lib/history-review'
import type { HistoryReview } from './lib/history-review'
import type { PostingBlock } from './lib/posting-blocks'

type View = 'Timetable' | 'Residents' | 'Requests' | 'Postings' | 'History review' | 'Issues'
const views: View[] = ['Timetable', 'Residents', 'Requests', 'Postings', 'History review', 'Issues']
const show = (value: string | null | undefined) => value || '—'
const source = (value: Source) => <small className="source">{sourceLabel(value)}</small>
const linked = sameSource

function revealElement(target: HTMLElement) {
  const rect = target.getBoundingClientRect()
  const offset = rect.height > window.innerHeight - 32 ? 16 : (window.innerHeight - rect.height) / 2
  return scrollToPosition(window.scrollY + rect.top - offset)
}

function ResidentDetail({ resident, workbook, onHistoryReview }: { resident: Resident; workbook: Workbook; onHistoryReview: () => void }) {
  const [tab, setTab] = useState('history')
  const [open, setOpen] = useState(false)
  const detail = useRef<HTMLDetailsElement>(null)
  useEffect(() => {
    if (open && detail.current) return revealElement(detail.current)
  }, [open])
  const requests = workbook.requests.filter((request) => request.posting_request?.trim() && linked(resident.source, request.matched_resident_source))
  const histories = workbook.histories.map((history) => ({ ...history, residents: history.residents.filter((person) => linked(resident.source, person.matched_resident_source)) })).filter((history) => history.residents.length)
  return <details ref={detail} name="resident-reviews" className="resident-detail" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>Review {resident.name || resident.mcr || 'resident'}</summary>
    <div className="resident-content">
      <dl className="resident-facts">
        <div><dt>MCR</dt><dd>{show(resident.mcr)}</dd></div>
        <div><dt>Residency year</dt><dd>{show(resident.residency_year)}</dd></div>
        <div><dt>Intake</dt><dd>{show(resident.intake)}</dd></div>
        <div><dt>Email</dt><dd>{show(resident.email)}</dd></div>
        <div><dt>MOM number</dt><dd>{show(resident.mom_number)}</dd></div>
      </dl>
      {resident.remarks && <p className="record-note">{resident.remarks}</p>}
      {source(resident.source)}
      <h3>Linked requests</h3>
      {requests.length ? requests.map((request, index) => <div className="record" key={index}><p>{show(request.posting_request)}</p><p className="muted">{show(request.period)}{request.remarks && ` · ${request.remarks}`}</p>{source(request.source)}</div>) : <p className="muted">No safely matched requests in this workbook.</p>}
      <div className="resident-tabs" role="group" aria-label="Resident records"><button type="button" className={`button ${tab === 'history' ? '' : 'button-secondary'}`} aria-pressed={tab === 'history'} onClick={() => setTab('history')}>Recorded history</button><button type="button" className={`button ${tab === 'requirements' ? '' : 'button-secondary'}`} aria-pressed={tab === 'requirements'} onClick={() => setTab('requirements')}>Requirements</button></div>
      {tab === 'requirements' ? open && <ResidentRequirements resident={resident} workbook={workbook} onHistoryReview={onHistoryReview} /> : <>
      <h3>Recorded history</h3>
      <p className="muted">Workbook records only. These entries do not establish credited or completed training. Unresolved identity matches appear in Issues.</p>
      {histories.length ? histories.map((history) => <div className="history-year" key={history.sheet}>
        <h4>{history.year}–{history.year + 1}</h4>
        {history.residents.map((person, index) => <div key={index}>{source(person.source)}<div className="history-months">{person.postings.map((posting) => <div key={posting.month}><span>{monthLabel(posting.month)}</span><p className={posting.status === 'loa' ? 'posting-value loa' : undefined}>{posting.status === 'loa' ? 'LOA' : posting.status === 'blank' ? 'No entry' : posting.value}</p>{source(posting.source)}</div>)}</div>{person.remarks && <p className="record-note">{person.remarks}</p>}</div>)}
      </div>) : <p className="muted">No safely matched historical records in this workbook.</p>}
      </>}
    </div>
  </details>
}

function matchesResident(query: string, name: string | null, mcr: string | null) {
  return `${name || ''} ${mcr || ''}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
}

function Review({ workbook, view, query, year, onHistoryReview, historyResident, draftState }: { workbook: Workbook; view: View; query: string; year: number; onHistoryReview: (resident: Resident) => void; historyResident: string; draftState: DraftState }) {
  const matches = (name: string | null, mcr: string | null) => matchesResident(query, name, mcr)
  const residents = workbook.residents.filter((resident) => matches(resident.name, resident.mcr))
  if (view === 'Issues') return <div className="review-content"><h2 className="issues-heading">Import issues <span className={`badge issue-badge ${(workbook.issues?.length || 0) + workbook.warnings.length > 0 ? 'issue-badge-warning' : 'issue-badge-neutral'}`} aria-label={`${(workbook.issues?.length || 0) + workbook.warnings.length} import issues`}>{(workbook.issues?.length || 0) + workbook.warnings.length}</span></h2>
    <ImportIssues issues={workbook.issues || []} warnings={workbook.warnings} />
  </div>
  if (view === 'History review') return <HistoricalPostingReview workbook={workbook} initialQuery={historyResident} />
  if (view === 'Postings') return <PostingReference workbook={workbook} />
  if (view === 'Requests') {
    const requests = workbook.requests.filter((request) => request.posting_request?.trim() && matches(request.name, request.mcr))
    const pending = year === workbook.target_year && draftState.draft && ['optimal', 'feasible'].includes(draftState.draft.status)
      ? draftState.draft.residents.flatMap((person) => person.requests || []).filter((outcome) => outcome.status === 'pending') : []
    return <><p className="table-note">Requests are not assigned to a planning year. The selected year changes resident links, not request dates or the recorded request rows.</p>{requests.length ? <div className="table-scroll"><table><caption className="sr-only">Workbook posting requests</caption><thead><tr><th>Resident</th><th>Request</th><th>Period</th><th>Remarks / source</th></tr></thead><tbody>{requests.map((request, index) => <tr key={index}><th scope="row">{show(request.name)}<small>{show(request.mcr)}</small></th><td>{show(request.posting_request)}</td><td>{show(request.period)}</td><td>{show(request.remarks)}{source(request.source)}<small>Identity: {request.match_status || 'Unresolved'}</small>{pending.filter((outcome) => sameSource(outcome.request.source, request.source)).map((outcome, i) => <small key={i}>Draft pending: {outcome.reason}</small>)}</td></tr>)}</tbody></table></div> : <p className="empty-note">No requests match this search.</p>}</>
  }
  if (!residents.length) return <p className="empty-note">{workbook.residents.length ? 'No residents match this search.' : 'No resident rows were found for this planning year.'}</p>
  return <div className="resident-list">{residents.map((resident) => <ResidentDetail key={JSON.stringify(resident.source)} resident={resident} workbook={workbook} onHistoryReview={() => onHistoryReview(resident)} />)}</div>
}

const postingCategoryLabels = { core: 'Core', elective: 'Elective', loa: 'LOA', unresolved: 'Unresolved', unallocated: 'Unallocated', requirements_completed: 'Requirements completed' }

function residentRowId(source: Source) {
  return `timetable-resident-${encodeURIComponent(JSON.stringify(source.kind ? [source.kind, source.slot_id] : [source.sheet, source.row]))}`
}

function Timetable({ residents, workbook, year, years, onYearChange, draftState, breakdownHost, onReady, importLoading, filters, actions, exportError, focusSource }: {
  residents: Resident[]; workbook: Workbook; year: number; years: number[]; onYearChange: (year: number) => void
  importLoading: boolean; draftState: DraftState; breakdownHost: HTMLDivElement | null; onReady: (target: HTMLElement) => (() => void) | undefined
  filters: ReactNode; actions: ReactNode; exportError: string | undefined; focusSource: Source | null
}) {
  const { draft, error: draftError, failedAttempt } = draftState
  const timetable = useRef<HTMLDivElement>(null)
  const focusedSource = useRef<Source | null>(null)
  const beforeGeneration = useRef<{ draft: DraftSchedule | null } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [loaded, setLoaded] = useState<{ workbook: Workbook; attempt: number; data: HistoryReview } | null>(null)
  const [failure, setFailure] = useState<{ workbook: Workbook; attempt: number; message: string } | null>(null)
  useEffect(() => {
    if (importLoading) return
    const controller = new AbortController()
    const changed = (event: StorageEvent) => { if (event.key === STORAGE_KEY || event.key === null) setAttempt((value) => value + 1) }
    window.addEventListener('storage', changed)
    void (async () => {
      try {
        const saved = readReviewStore(window.localStorage)
        if (saved.error) throw new Error(saved.error)
        const data = await evaluateHistory(workbook, saved.store, controller.signal, 'timetable')
        if (!controller.signal.aborted) setLoaded({ workbook, attempt, data })
      } catch (problem) {
        if (!controller.signal.aborted) setFailure({ workbook, attempt, message: problem instanceof Error ? problem.message : 'Catalogue labels could not be loaded.' })
      }
    })()
    return () => { controller.abort(); window.removeEventListener('storage', changed) }
  }, [workbook, attempt, importLoading])
  const resolution = !importLoading && loaded?.workbook === workbook && loaded.attempt === attempt ? loaded.data : null
  const error = !importLoading && failure?.workbook === workbook && failure.attempt === attempt ? failure.message : ''
  const loading = importLoading || (!resolution && !error)
  useLayoutEffect(() => {
    if (loading || !focusSource || focusedSource.current === focusSource) return
    const target = document.getElementById(residentRowId(focusSource))
    if (target && timetable.current?.contains(target)) {
      focusedSource.current = focusSource
      target.focus({ preventScroll: true })
      target.scrollIntoView({ block: 'center', inline: 'nearest' })
    }
  }, [focusSource, loading])
  useEffect(() => {
    if (importLoading || year !== workbook.target_year) { beforeGeneration.current = null; return }
    if (draftState.busy) { beforeGeneration.current ??= { draft }; return }
    if (loading || !beforeGeneration.current) return
    const previous = beforeGeneration.current.draft
    beforeGeneration.current = null
    const grid = timetable.current
    if (draft && draft !== previous && grid && grid.getBoundingClientRect().top >= window.innerHeight) return revealElement(grid)
  }, [draft, draftState.busy, importLoading, loading, workbook.target_year, year])
  useEffect(() => {
    if (loading || !breakdownHost || !timetable.current) return
    let stop: (() => void) | undefined
    // Let the final timetable and breakdown paint before starting the scroll.
    let frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => {
        if (timetable.current) stop = onReady(timetable.current)
      })
    })
    return () => { cancelAnimationFrame(frame); stop?.() }
  }, [loading, breakdownHost, onReady, workbook])
  const availableYears = [...years].sort((a, b) => a - b)
  const yearIndex = availableYears.indexOf(year)
  const words = (value: string) => value.split(/(\s+)/).map((word, index) => /\s/.test(word) ? word : <span className="posting-word" key={index}>{word}</span>)
  const range = (block: PostingBlock) => block.length === 1 ? monthLabel(block[0].month) : `${monthLabel(block[0].month)} – ${monthLabel(block[block.length - 1].month)}`
  return <>
    <div className="timetable-toolbar">
      <div>
        <div className="year-navigation" role="group" aria-label="Timetable planning year">
          <h2 className="year-range">Jul {year} – Jun {year + 1}</h2>
          <button type="button" className="button button-secondary year-arrow" aria-label="Previous planning year" disabled={importLoading || yearIndex <= 0} onClick={() => onYearChange(availableYears[yearIndex - 1])}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m10 3-5 5 5 5" /></svg></button>
          <button type="button" className="button button-secondary year-arrow" aria-label="Next planning year" disabled={importLoading || yearIndex < 0 || yearIndex >= availableYears.length - 1} onClick={() => onYearChange(availableYears[yearIndex + 1])}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3 5 5-5 5" /></svg></button>
        </div>
        {draft && !draftState.busy && <DraftTimer draft={draft} startedAt={null} elapsedSeconds={draftState.elapsedSeconds} />}
      </div>
      {actions}
    </div>
    {filters}
    {failedAttempt && <div className="draft-feedback" role="status">
      {draft && <p>The current draft is still available.</p>}
      <p>{failedAttempt.status === 'blocked' ? 'Draft generation blocked. Resolve the input issues below, then generate again.' : failedAttempt.status === 'infeasible' ? 'No feasible draft meets the current constraints. Review availability, posting eligibility and outstanding training.' : failedAttempt.status === 'unknown' ? 'No solution was found within the time limit. Retry or review the inputs.' : 'The scheduling model could not be validated. Check the workbook inputs and retry.'}</p>
      {failedAttempt.blockers.length > 0 && <ul>{failedAttempt.blockers.map((blocker, index) => <li key={index}>{draftBlockerLabel(blocker, workbook)}</li>)}</ul>}
    </div>}
    {draftError && <p className="draft-error" role="alert">{draftError}</p>}
    {exportError && <p className="draft-error" role="alert">{exportError}</p>}
    {error && <div className="timetable-label-error" role="alert"><p>Catalogue labels are unavailable. Original labels are shown. {error}</p><button className="button button-secondary" type="button" onClick={() => setAttempt((value) => value + 1)}>Retry catalogue labels</button></div>}
    <div ref={timetable} aria-busy={loading}>
    {loading ? <><span className="sr-only" role="status">{importLoading ? 'Loading workbook data' : 'Loading catalogue labels'}</span><Skeleton /></> : !residents.length ? <p className="empty-note">{workbook.residents.length ? 'No residents match this search or request filter.' : 'No resident rows were found for this planning year.'}</p> : <TimetableGrid><table>
      <caption className="sr-only">{draft ? 'Draft' : 'Imported'} timetable for July {workbook.target_year} to June {workbook.target_year + 1}. Blank cells are labelled unallocated.</caption>
      <colgroup><col className="resident-column" />{workbook.months.map((month) => <col key={month.month} />)}</colgroup>
      <thead><tr><th scope="col">Resident</th>{workbook.months.map((month) => <th scope="col" key={month.month} title={sourceLabel(month.source)}>{monthLabel(month.month)}</th>)}</tr></thead>
      <tbody>{groupDraftResidents(residents, draft, resolution?.entries).map((resident) => {
        const { rows, counts, indicator: requestIndicator } = requestSummary(resident, draft)
        const rowId = residentRowId(resident.source)
        return <tr key={rowId}>
          <th scope="row" id={rowId} tabIndex={-1}>
            <span>{words(show(resident.name))}</span><small>{words(`${show(resident.mcr)} · ${show(draftResidentYear(resident, draft))}`)}</small>
            {rows.length > 0 && <div className="request-counts">{(['met', 'not_met', 'pending'] as const).map((status) => {
              const count = counts[status]
              const label = status === 'not_met' ? 'not met' : status
              return count > 0 && <RequestDetails className={`request-count ${status}`} key={status} name={show(resident.name)} rows={rows.filter((row) => row.status === status)} hint={`${count} ${label} - click for details`}>{count} {label}</RequestDetails>
            })}</div>}
          </th>
          {groupPostings(draftPostings(resident, draft)).map((block) => {
            const status = block[0].status
            const display = postingDisplay(block, 'catalogue', resolution?.entries)
            const value = display.label
            const category = postingCategory(display, status)
            const classification = category === 'requirements_completed' ? '' : ` - ${postingCategoryLabels[category]}`
            const qualifiers = display.markers.filter((marker) => marker !== 'Elective')
            const hoverName = category === 'elective' && !/\(\s*elective\s*\)/i.test(value) ? `${value} (Elective)` : value
            const hoverRange = range(block).replaceAll('Sept ', 'Sep ').replace('–', '-')
            const indicator = requestIndicator(block[0].month)
            const projection = category === 'requirements_completed' ? 'Draft projection - ' : ''
            const draftPrefix = projection || (block[0].draft ? 'Draft assignment - ' : '')
            return <td key={block[0].month} colSpan={block.length}><div className={`posting-value ${category}`} role="group"
              data-posting-tooltip={`${projection}${hoverName} • ${hoverRange}`}
              aria-label={`${show(resident.name)} - ${range(block)} - ${draftPrefix}${value}${classification}${qualifiers.length ? ` - ${qualifiers.join(', ')}` : ''}`}>
              <span className="posting-name">{value}</span>
              {indicator && <RequestDetails className={`request-indicator ${indicator.status}`} name={show(resident.name)} rows={[indicator]} hint={`${indicator.status === 'met' ? 'Request met' : 'Request not met'} - click for details`}><svg viewBox="0 0 16 16" aria-hidden="true">{indicator.status === 'met' ? <path d="m3 8 3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2" /> : <><path d="M8 2 15 14H1Z" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M8 6v4m0 2v.5" stroke="currentColor" strokeWidth="1.5" /></>}</svg></RequestDetails>}
              {qualifiers.length > 0 && <span className="posting-markers">{qualifiers.map((marker) => <span className={`posting-marker${marker === 'Remediation' ? ' posting-marker-remediation' : ''}`} key={marker}>{marker}</span>)}</span>}
            </div></td>
          })}
        </tr>
      })}</tbody>
    </table></TimetableGrid>}
    </div>
    {!loading && <ul className="posting-legend" aria-label="Posting colour legend">{Object.entries(postingCategoryLabels).map(([kind, label]) => <li key={kind}><span aria-hidden="true" className={`legend-marker legend-${kind}`} />{label}</li>)}</ul>}
    {!loading && breakdownHost && createPortal(<MonthlyBreakdown key={year} workbook={workbook} draft={draft} entries={resolution?.entries || []} />, breakdownHost)}
  </>
}

export default function App() {
  const input = useRef<HTMLInputElement>(null)
  const browse = useRef<HTMLButtonElement>(null)
  const review = useRef<HTMLElement>(null)
  const revealAfterUpload = useRef(false)
  const [file, setFile] = useState<File | null>(null)
  const [workbook, setWorkbook] = useState<Workbook | null>(null)
  const [year, setYear] = useState<number>()
  const [busy, setBusy] = useState(false)
  const [restoring, setRestoring] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<{ file: File; draft: DraftSchedule; message: string } | null>(null)
  const [storageError, setStorageError] = useState('')
  const currentSession = useRef<{ file: File; workbook: Workbook } | null>(null)
  const [loadingHeight, setLoadingHeight] = useState<number>()
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [dragging, setDragging] = useState(false)
  const [view, setView] = useState<View>('Timetable')
  const [query, setQuery] = useState('')
  const [focusSource, setFocusSource] = useState<Source | null>(null)
  const [historyResident, setHistoryResident] = useState('')
  const [breakdownHost, setBreakdownHost] = useState<HTMLDivElement | null>(null)
  const draftMemory = useDraftSchedule(workbook, busy || restoring, year)
  const { getSavedResult, restore: restoreDraft } = draftMemory
  const persistCurrent = useCallback(() => {
    const current = currentSession.current
    const record = current ? { version: 1 as const, ...current, fileName: current.file.name,
      lastModified: current.file.lastModified, draft: getSavedResult() } : null
    void saveSession(record).then(() => setStorageError('')).catch(() => setStorageError('Browser save failed. The current page still works, but these changes may not survive a refresh.'))
  }, [getSavedResult])
  const draftState = draftMemory
  function discardSavedDraft() { setExportError(null); draftMemory.discard(); persistCurrent() }
  useEffect(() => {
    let cancelled = false
    void restoreSession().then((saved) => {
      if (cancelled || !saved) return
      currentSession.current = { file: saved.file, workbook: saved.workbook }
      revealAfterUpload.current = saved.workbook.residents.length > 0
      setFile(saved.file); setWorkbook(saved.workbook); setYear(saved.workbook.target_year)
      if (saved.draft) restoreDraft(saved.draft)
    }).catch((problem: unknown) => {
      if (!cancelled) setStorageError(problem instanceof Error ? problem.message : 'The saved workbook could not be restored.')
    }).finally(() => { if (!cancelled) setRestoring(false) })
    return () => { cancelled = true }
  }, [restoreDraft])
  useEffect(() => {
    if (!restoring && currentSession.current) persistCurrent()
  }, [file, workbook, draftMemory.savedResult, restoring, persistCurrent])
  const hasDraft = draftState.draft?.status === 'optimal' || draftState.draft?.status === 'feasible'
  const exportSnapshot = useRef({ file, draft: draftState.draft })
  useLayoutEffect(() => { exportSnapshot.current = { file, draft: draftState.draft } }, [file, draftState.draft])
  const exportController = useRef<AbortController | null>(null)
  useEffect(() => () => { exportController.current?.abort(); exportSnapshot.current = { file: null, draft: null } }, [])
  async function downloadExcel() {
    const draft = draftState.draft
    if (!file || !workbook || !hasDraft || !draft || !draftState.canGenerate || draftState.pending || exporting) return
    const originalFile = file
    const targetYear = workbook.target_year
    const controller = new AbortController()
    exportController.current = controller
    setExporting(true); setExportError(null)
    try {
      const { blob } = await exportDraft(originalFile, targetYear, draft, controller.signal)
      if (exportSnapshot.current.file === originalFile && exportSnapshot.current.draft === draft) {
        downloadDraft(blob, originalFile.name, targetYear)
      }
    } catch (problem) {
      if (exportSnapshot.current.file === originalFile && exportSnapshot.current.draft === draft) setExportError({ file: originalFile, draft, message: problem instanceof Error ? problem.message : 'Excel export failed. Retry.' })
    } finally {
      if (exportController.current === controller) { exportController.current = null; setExporting(false) }
    }
  }
  const [requestSelection, setRequestSelection] = useState<{ draft: DraftSchedule; status: RequestStatus | null } | null>(null)
  const requestFilter = hasDraft && requestSelection?.draft === draftState.draft ? requestSelection.status : null

  const matchingResidents = workbook?.residents.filter((resident) => matchesResident(query, resident.name, resident.mcr)) || []
  const timetableResidents = filterRequestResidents(matchingResidents, draftState.draft, requestFilter)
  function selectRequestFilter(status: RequestStatus | null) {
    if (draftState.draft) setRequestSelection({ draft: draftState.draft, status })
  }
  function findInTimetable(source: Source) {
    const resident = workbook?.residents.find((person) => sameSource(person.source, source))
    if (!resident) return
    if (!matchesResident(query, resident.name, resident.mcr)) setQuery('')
    if (requestFilter && !requestSummary(resident, draftState.draft).counts[requestFilter]) setRequestSelection(null)
    setFocusSource({ ...source })
  }

  const revealTimetable = useCallback((target: HTMLElement) => {
    if (!revealAfterUpload.current) return
    revealAfterUpload.current = false
    const card = review.current || target
    return scrollToPosition(window.scrollY + card.getBoundingClientRect().top - 16)
  }, [])

  async function load(nextFile: File, nextYear?: number, reveal = false) {
    setLoadingHeight(review.current?.getBoundingClientRect().height)
    setBusy(true); setError(''); setStatus(''); setFocusSource(null)
    try {
      const result = await importWorkbook(nextFile, nextYear)
      revealAfterUpload.current = reveal
      if (reveal) { draftMemory.discard(); setView('Timetable'); setQuery('') }
      currentSession.current = { file: nextFile, workbook: result }
      setWorkbook(result); setFile(nextFile); setYear(result.target_year)
      setStatus('')
    } catch (problem: unknown) {
      setYear(workbook?.target_year ?? year)
      setError(problem instanceof Error ? problem.message : 'Workbook import failed. Please try again.')
      setStatus(file ? 'The previous import is still available.' : '')
    } finally { setBusy(false) }
  }
  function choose(files: File[]) {
    if (busy || restoring || !files.length) return
    const problem = workbookError(files)
    if (problem) { setError(problem); return }
    void load(files[0], undefined, true)
  }
  function selectYear(nextYear: number) {
    if (file && !busy && !restoring) { setYear(nextYear); void load(file, nextYear) }
  }
  const years = [...new Set(workbook?.available_years.map((item) => item.year) || [])].sort((a, b) => b - a)
  const issueCount = workbook ? (workbook.issues?.length || 0) + workbook.warnings.length : 0
  return <>
    <a href="#main" className="skip-link">Skip to workspace</a>
    <header className="site-header"><a href="/" className="brand" aria-label="PSY Residency Scheduler home"><span className="brand-mark" aria-hidden="true">PSY</span><span>Residency scheduler</span></a></header>
    <main id="main" className="site-main" tabIndex={-1}>
      <div className="page-heading"><h1>Posting timetable</h1><p>NHG Psychiatry Residency Programme</p></div>
      <section className="workspace-panel" aria-labelledby="import-title">
        <div className="panel-heading"><h2 id="import-title">Workbook import</h2><span className="badge">Local browser storage</span></div>
        <div className={`workbook-chooser ${dragging ? 'is-dragging' : ''}`} onDragOver={(event) => { event.preventDefault(); if (!busy) setDragging(true) }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false) }} onDrop={(event) => { event.preventDefault(); setDragging(false); choose(Array.from(event.dataTransfer.files)) }}>
          <div className="upload-copy">{file ? <><h3 className="filename">{file.name}</h3><p>{file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / 1024 / 1024).toFixed(1)} MB`} · Imported for {workbook?.target_year}–{workbook && workbook.target_year + 1}</p></> : <><h3>Start with your programme workbook</h3><p>Choose or drop one .xlsx workbook, up to 10 MB.</p></>}<p className="session-note">Your latest successful import and completed draft are kept in this browser. Remove clears the import and draft. Historical review decisions are saved separately.</p></div>
          <div className="upload-actions"><input ref={input} type="file" accept=".xlsx" hidden disabled={busy || restoring} aria-label="Programme workbook" onChange={(event) => { choose(Array.from(event.target.files || [])); event.target.value = '' }} /><button ref={browse} className="button" type="button" disabled={busy || restoring} aria-describedby={error ? 'import-error' : undefined} onClick={() => input.current?.click()}>{restoring ? 'Restoring workbook...' : busy ? 'Reading workbook…' : file ? 'Replace workbook' : 'Choose workbook'}</button>{file && <button className="button button-secondary" type="button" disabled={busy} onClick={() => { currentSession.current = null; discardSavedDraft(); setFile(null); setWorkbook(null); setYear(undefined); setError(''); setQuery(''); setStatus('Import removed. Choose or drop another workbook.'); browse.current?.focus(); }}>Remove</button>}</div>
        </div>
        <div className="import-feedback"><p role="status" aria-live="polite">{restoring ? 'Restoring saved workbook...' : draftMemory.notice || status}</p>{storageError && <p role="status" className="error-message">{storageError}</p>}{error && <p id="import-error" role="alert" className="error-message">{error}{workbook && ' Your previous import is unchanged.'}</p>}</div>
      </section>
      {(workbook || busy) && <section ref={review} style={{ minHeight: busy ? loadingHeight : undefined }} className="workspace-panel review-panel" aria-label="Workbook review" aria-busy={busy}>
        <nav className="view-nav" aria-label="Workbook views">{views.map((item) => <button type="button" key={item} className={view === item ? 'active' : ''} aria-current={view === item ? 'page' : undefined} disabled={busy} onClick={() => { setHistoryResident(''); setFocusSource(null); setView(item) }}>{item}{item === 'Issues' && issueCount ? ` (${issueCount})` : ''}</button>)}</nav>
        {(view === 'Residents' || view === 'Requests') && <div className="search-toolbar">
          <label>Planning year<select value={year ?? ''} disabled={busy} onChange={(event) => selectYear(Number(event.target.value))}>{years.map((value) => <option key={value} value={value}>Jul {value} - Jun {value + 1}</option>)}</select></label>
          <SearchField id="resident-search" label="Search residents" placeholder="Name or MCR number" value={query} disabled={busy} onChange={setQuery} />
          {workbook && <p className="sheet-label">Source: {workbook.target_sheet}</p>}
        </div>}
        {workbook && view === 'Timetable' ? <Timetable residents={timetableResidents} workbook={workbook} year={year ?? workbook.target_year} years={years}
          onYearChange={selectYear} draftState={draftState} breakdownHost={breakdownHost} onReady={revealTimetable} importLoading={busy || restoring}
          focusSource={focusSource} exportError={exportError && exportError.file === file && exportError.draft === draftState.draft ? exportError.message : undefined}
          actions={<DraftActions state={draftState} workbook={workbook} yearLabel={`Jul ${workbook.target_year} – Jun ${workbook.target_year + 1}`} exporting={exporting} onExport={() => void downloadExcel()} onDiscard={discardSavedDraft} onFind={findInTimetable} />}
          filters={<div className="search-toolbar timetable-filters">
            <SearchField id="resident-search" label="Search residents" placeholder="Name or MCR" value={query} disabled={busy} onChange={setQuery} />
            <RequestOutcomeFilter draft={draftState.draft} selected={requestFilter} onChange={selectRequestFilter} disabled={busy} />
          </div>}
        /> : workbook && !busy ? <Review workbook={workbook} view={view} query={query} year={year ?? workbook.target_year}
          onHistoryReview={(resident) => { setHistoryResident(resident.mcr || resident.name || ''); setView('History review') }}
          historyResident={historyResident} draftState={draftState}
        /> : busy && <><span className="sr-only" role="status">Loading workbook data</span><Skeleton /></>}
      </section>}
      {workbook && view === 'Timetable' && <div ref={setBreakdownHost} />}
    </main>
    {workbook && !busy && ['Residents', 'Requests', 'Postings'].includes(view) && <ScrollToTop key={view} />}
  </>
}
