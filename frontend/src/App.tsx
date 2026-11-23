import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import type { DragEvent, KeyboardEvent, ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { exportDraft, downloadDraft } from './lib/draft-export'
import { restoreSession, saveSession } from './lib/workbook-session'
import { useDraftSchedule } from './lib/use-draft-schedule'
import type { DraftState } from './lib/use-draft-schedule'
import RequestDetails from './components/RequestDetails'
import RequestOutcomeFilter from './components/RequestOutcomeFilter'
import type { DraftChangeIssue, DraftSchedule, RequestStatus } from './lib/draft-schedule'
import { draftBlockerLabel, draftInsertion, draftPostings, draftPreviewIssuesForRow, draftResidentYear, groupDraftResidents, requestSummary, filterRequestResidents, isUsableDraft } from './lib/draft-schedule'
import { draftDestinationError, issuesForCell, useDraftBlockEditing } from './lib/use-draft-block-editing'
import type { DraftBlock, DraftCell, DraftDestination } from './lib/use-draft-block-editing'
import DraftBlockEditor, { DraftBlockFlagIcon, DraftBlockReasons, DraftMoveFeedback } from './components/DraftBlockEditor'
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
import { emptyStore, evaluateHistory, prepareYear, readReviewStore, reviewSignature, REVIEW_CHANGED, STORAGE_KEY } from './lib/history-review'
import type { HistoryReview } from './lib/history-review'
import type { PostingBlock } from './lib/posting-blocks'

type View = 'Timetable' | 'Residents' | 'Requests' | 'Postings' | 'History review' | 'Issues'
const views: View[] = ['Timetable', 'Residents', 'Requests', 'Postings', 'History review', 'Issues']
const show = (value: string | null | undefined) => value || '—'
const source = (value: Source) => <small className="source">{sourceLabel(value)}</small>
const linked = sameSource

function dragDestination(event: DragEvent<HTMLTableCellElement>, cell: DraftCell): DraftDestination {
  if (!cell.months.length) return cell
  const { left, right, width } = event.currentTarget.getBoundingClientRect()
  const edge = width * 0.3
  const side = event.clientX - left <= edge ? 'before' : right - event.clientX <= edge ? 'after' : undefined
  return { ...cell, side }
}

function RequestIndicatorIcon({ status }: { status: RequestStatus }) {
  return <svg viewBox="0 0 16 16" aria-hidden="true">{status === 'met'
    ? <path d="m3 8 3 3 7-7" fill="none" stroke="currentColor" strokeWidth="2" />
    : <><path d="M8 2 15 14H1Z" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M8 6v4m0 2v.5" stroke="currentColor" strokeWidth="1.5" /></>}</svg>
}

function draftIssueStyle(issues: DraftChangeIssue[]) {
  return issues.some((issue) => issue.severity === 'hard') ? 'hard' : issues.length ? 'soft' : ''
}

function DraftInsertionPreview({ months, preview, held, anchorIndex, anchorLength, source, warnings, requestIndicator }: {
  months: DraftSchedule['residents'][number]['months']; preview: (string | undefined)[] | null
  held: string; anchorIndex: number; anchorLength: number
  source: Source; warnings: DraftChangeIssue[]; requestIndicator: ReturnType<typeof requestSummary>['indicator']
}) {
  const parts: { start: string; index: number; length: number; key: string }[] = []
  const counts = new Map<string, number>()
  const positions = preview ?? months.map((month) => month.block_start)
  positions.forEach((start, index) => {
    if (!start) return
    const previous = parts.at(-1)
    if (previous?.start === start && previous.index + previous.length === index) {
      previous.length++
    } else {
      const count = counts.get(start) ?? 0
      counts.set(start, count + 1)
      parts.push({ start, index, length: 1, key: `${start}-${count}` })
    }
  })
  return <div className="draft-insertion-preview" aria-hidden="true" data-visible={!!preview}>
    {parts.map(({ start, index, length, key }) => {
      const block = months.filter((month) => month.block_start === start)
      const placeholder = start === held
      const issueStyle = placeholder ? '' : draftIssueStyle(issuesForCell(warnings, source, block.map((month) => month.month)))
      const precedingMonths = positions.slice(0, index).filter((position) => position === start).length
      const request = placeholder ? undefined : requestIndicator(block[precedingMonths].month)
      return <div key={key} className={`posting-value ${block[0].target?.category ?? 'core'} ${issueStyle}${placeholder ? 'draft-insertion-gap' : ''}`}
        style={{ transform: `translateX(${100 * (index - anchorIndex) / anchorLength}cqw)`, width: `calc(${100 * length / anchorLength}% - 8px)` }}>
        {!placeholder && <span className="posting-name">{block[0].label}</span>}
        {issueStyle && <span className={`draft-block-flag ${issueStyle}`}><DraftBlockFlagIcon /></span>}
        {request && <span className={`request-indicator ${request.status}`}><RequestIndicatorIcon status={request.status} /></span>}
      </div>
    })}
  </div>
}

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
    const pending = year === workbook.target_year && isUsableDraft(draftState.draft)
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

type TimetableLabels = { signature: string; data: HistoryReview }

function subscribeToReviews(changed: () => void) {
  const storageChanged = (event: StorageEvent) => { if (event.key === STORAGE_KEY || event.key === null) changed() }
  window.addEventListener('storage', storageChanged)
  window.addEventListener(REVIEW_CHANGED, changed)
  return () => {
    window.removeEventListener('storage', storageChanged)
    window.removeEventListener(REVIEW_CHANGED, changed)
  }
}

function reviewSnapshot() {
  try { return window.localStorage.getItem(STORAGE_KEY) } catch { return undefined }
}

function readTimetableReviews(raw: ReturnType<typeof reviewSnapshot>) {
  if (raw === undefined) return { store: emptyStore(), signature: '', error: 'Browser storage is unavailable.' }
  const saved = readReviewStore({ getItem: () => raw })
  return { ...saved, signature: reviewSignature(saved.store) }
}

function Timetable({ residents, workbook, year, years, onYearChange, draftState, breakdownHost, onReady, importLoading, exporting, filters, actions, exportError, focusSource, labels, onLabels }: {
  residents: Resident[]; workbook: Workbook; year: number; years: number[]; onYearChange: (year: number) => void
  importLoading: boolean; exporting: boolean; draftState: DraftState; breakdownHost: HTMLDivElement | null
  onReady: (target: HTMLElement, workbook: Workbook, labelsReady: boolean) => (() => void) | undefined
  filters: ReactNode; actions: ReactNode; exportError: string | undefined; focusSource: Source | null
  labels: TimetableLabels | undefined; onLabels: (workbook: Workbook, labels: TimetableLabels) => void
}) {
  const { draft, error: draftError, failedAttempt } = draftState
  const timetable = useRef<HTMLDivElement>(null)
  const focusedSource = useRef<Source | null>(null)
  const beforeGeneration = useRef<{ draft: DraftSchedule | null } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const rawReviews = useSyncExternalStore(subscribeToReviews, reviewSnapshot)
  const savedReviews = useMemo(() => readTimetableReviews(rawReviews), [rawReviews])
  const [failure, setFailure] = useState<{ workbook: Workbook; review: typeof savedReviews; attempt: number; message: string } | null>(null)
  const resolution = !importLoading && !savedReviews.error && labels?.signature === savedReviews.signature ? labels.data : undefined
  useEffect(() => {
    if (importLoading || savedReviews.error || resolution) return
    const controller = new AbortController()
    void evaluateHistory(workbook, savedReviews.store, controller.signal, 'timetable').then((data) => {
      if (controller.signal.aborted) return
      const raw = reviewSnapshot()
      const latest = raw === rawReviews ? savedReviews : readTimetableReviews(raw)
      if (latest.error || latest.signature !== savedReviews.signature) return
      onLabels(workbook, { signature: savedReviews.signature, data })
    }).catch((problem: unknown) => {
      if (!controller.signal.aborted) setFailure({ workbook, review: savedReviews, attempt, message: problem instanceof Error ? problem.message : 'Catalogue labels could not be loaded.' })
    })
    return () => controller.abort()
  }, [workbook, onLabels, rawReviews, savedReviews, attempt, importLoading, resolution])
  const error = !importLoading && !resolution ? savedReviews.error || (failure?.workbook === workbook && failure.review === savedReviews && failure.attempt === attempt ? failure.message : '') : ''
  const loading = importLoading || (!resolution && !error)
  const hasEditOptions = !!draft?.edit_options?.length
  const canEdit = hasEditOptions && !loading && !savedReviews.error && !draftState.pending && !exporting
  const editing = useDraftBlockEditing(workbook, savedReviews.store, draft, !canEdit, draftState.applyChange)
  const moveSource = (editing.move ?? editing.released)?.from.source
  const editor = editing.editor
  const editorResident = editor && draft?.residents.find((person) => sameSource(person.source, editor.source))
  const editorCurrent = editorResident?.months.find((month) => month.month === editor?.start)?.target?.source

  function dragOver(event: DragEvent<HTMLTableCellElement>, cell: DraftCell) {
    const move = editing.moving.current
    if (!move || move.keyboard) return
    event.preventDefault()
    editing.selectDestination(dragDestination(event, cell))
    // Allow the release event so a blocked drop can explain itself at the target.
    event.dataTransfer.dropEffect = sameSource(move.from.source, cell.source) && move.from.start === cell.start ? 'none' : 'move'
  }

  function dropOnCell(event: DragEvent<HTMLTableCellElement>, cell: DraftCell) {
    if (!editing.moving.current || editing.moving.current.keyboard) return
    event.preventDefault()
    editing.drop(dragDestination(event, cell), event.currentTarget)
  }

  function keyboardMove(event: KeyboardEvent<HTMLButtonElement>, block: DraftBlock, months: NonNullable<typeof draft>['residents'][number]['months']) {
    const move = editing.moving.current
    if (event.key === 'Tab' && editing.released?.keyboard && editing.checking) {
      editing.dismissDrop(false)
      return
    }
    if (event.key === 'Escape' && editing.released?.keyboard && editing.checking) {
      event.preventDefault()
      editing.dismissDrop()
      return
    }
    if (editing.released?.keyboard && editing.released.anchor.contains(event.currentTarget) && (event.key === 'Enter' || event.key === ' ')) {
      event.preventDefault()
      return
    }
    if (!move && event.key === ' ') {
      event.preventDefault()
      if (!event.repeat) editing.startMove(block, true)
      return
    }
    if (!move?.keyboard) return
    if (event.key === 'Escape' || event.key === 'Tab') {
      if (event.key === 'Escape') event.preventDefault()
      editing.endKeyboardMove(event.key === 'Escape')
      return
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      if (!event.repeat && editing.destination) editing.drop(editing.destination, event.currentTarget.closest('td') ?? event.currentTarget)
      return
    }
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    event.preventDefault()
    const buttons = [...(event.currentTarget.closest('tr')?.querySelectorAll<HTMLButtonElement>('[data-draft-start]') ?? [])]
    const blocks = [...new Set(buttons.map((button) => button.dataset.draftStart))]
    const right = event.key === 'ArrowRight'
    const next = blocks[blocks.indexOf(block.start) + (right ? 1 : -1)]
    const button = next && buttons.find((item) => item.dataset.draftStart === next)
    if (!next || !button) return
    button.focus({ preventScroll: true })
    button.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    const nextMonths = months.filter((month) => month.block_start === next)
    editing.selectDestination({ source: block.source, start: next, label: nextMonths[0].label ?? '',
      months: nextMonths.map((month) => month.month), side: event.shiftKey ? (right ? 'after' : 'before') : undefined })
  }
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
        if (timetable.current) stop = onReady(timetable.current, workbook, !!resolution)
      })
    })
    return () => { cancelAnimationFrame(frame); stop?.() }
  }, [loading, breakdownHost, onReady, workbook, resolution])
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
        {draft && !draftState.busy && (draft.status === 'edited' ? <span className="draft-edited-label">Edited draft</span> : <DraftTimer draft={draft} startedAt={null} elapsedSeconds={draftState.elapsedSeconds} />)}
      </div>
      {actions}
    </div>
    {filters}
    {draft && !hasEditOptions && <p className="table-note draft-edit-controls">Regenerate this draft to edit its posting blocks.</p>}
    {hasEditOptions && <details className="draft-edit-controls"><summary>Timetable controls</summary>
      <p>Select a posting to edit it. Drag to a block’s edge to insert before or after it, or to the centre of an equal-length block to swap. With the keyboard, press Space to pick up a block, use the arrow keys to choose a swap or hold Shift while using the arrows to insert, then press Enter to drop or Escape to cancel.</p>
    </details>}
    <p className="sr-only" role="status">{editing.announcement}</p>
    {failedAttempt && <div className="draft-feedback" role="status">
      {draft && <p>The current draft is still available.</p>}
      <p>{failedAttempt.status === 'blocked' ? 'Draft generation blocked. Resolve the input issues below, then generate again.' : failedAttempt.status === 'infeasible' ? 'No feasible draft meets the current constraints. Review availability, posting eligibility and outstanding training.' : failedAttempt.status === 'unknown' ? 'No solution was found within the time limit. Retry or review the inputs.' : 'The scheduling model could not be validated. Check the workbook inputs and retry.'}</p>
      {failedAttempt.blockers.length > 0 && <ul>{failedAttempt.blockers.map((blocker, index) => <li key={index}>{draftBlockerLabel(blocker, workbook)}</li>)}</ul>}
    </div>}
    {draftError && <p className="draft-error" role="alert">{draftError}</p>}
    {exportError && <p className="draft-error" role="alert">{exportError}</p>}
    {error && <div className="timetable-label-error" role="alert"><p>Catalogue labels are unavailable. Original labels are shown. {error}</p><button className="button button-secondary" type="button" onClick={() => setAttempt((value) => value + 1)}>Retry catalogue labels</button></div>}
    <div ref={timetable} aria-busy={loading} onDragOver={(event) => {
      if (!event.defaultPrevented && !editing.moving.current?.keyboard) editing.selectDestination(null)
    }} onDragLeave={(event) => {
      if (!(event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) && !editing.moving.current?.keyboard) editing.selectDestination(null)
    }}>
    {loading ? <><span className="sr-only" role="status">{importLoading ? 'Loading workbook data' : 'Loading catalogue labels'}</span><Skeleton /></> : !residents.length ? <p className="empty-note">{workbook.residents.length ? 'No residents match this search or request filter.' : 'No resident rows were found for this planning year.'}</p> : <TimetableGrid suppressTooltip={!!editing.move}><table>
      <caption className="sr-only">{draft ? 'Draft' : 'Imported'} timetable for July {workbook.target_year} to June {workbook.target_year + 1}. Blank cells are labelled unallocated.</caption>
      <colgroup><col className="resident-column" />{workbook.months.map((month) => <col key={month.month} />)}</colgroup>
      <thead><tr><th scope="col">Resident</th>{workbook.months.map((month) => <th scope="col" key={month.month} title={sourceLabel(month.source)}>{monthLabel(month.month)}</th>)}</tr></thead>
      <tbody>{groupDraftResidents(residents, draft, resolution?.entries).map((resident) => {
        const { rows, counts, indicator: requestIndicator } = requestSummary(resident, draft)
        const rowId = residentRowId(resident.source)
        const draftMonths = draft?.residents.find((item) => sameSource(item.source, resident.source))?.months ?? []
        const held = editing.move && sameSource(resident.source, editing.move.from.source) ? editing.move.from : null
        const destination = editing.destination
        const canSwap = held && destination && !destination.side && held.start !== destination.start && !draftDestinationError(held, destination)
        const insertion = held && destination?.side && sameSource(resident.source, destination.source)
          ? draftInsertion(draftMonths, held.start, destination.start, destination.side) : null
        const previewAnchor = draftMonths.findIndex((month) => month.block_start)
        const previewIssues = draftPreviewIssuesForRow(editing.preview?.issues ?? [], resident.source, moveSource, destination?.source)
        return <tr key={rowId} data-inserting={!!insertion?.changed}>
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
            const start = block[0].draftBlockStart
            const blockId = `${rowId}-${block[0].month}`
            const name = show(resident.name)
            const cellMonths = block.map((month) => month.month)
            const cell = { source: resident.source, start: start ?? block[0].month, leave: status === 'loa', label: value,
              months: start ? draftMonths.filter((month) => month.block_start === start).map((month) => month.month) : [] }
            const issueMonths = cell.months.length ? cell.months : cellMonths
            const atDestination = destination && sameSource(resident.source, destination.source) && cell.start === destination.start
            const swapping = atDestination && canSwap
            const aimed = atDestination && editing.released
            const changedIssues = aimed ? previewIssues : issuesForCell(previewIssues, resident.source, issueMonths)
            const savedIssues = issuesForCell(draft?.edit_warnings ?? [], resident.source, issueMonths)
            const issueStyle = draftIssueStyle(changedIssues.length ? changedIssues : savedIssues)
            const picked = held && start === held.start
            const warning = savedIssues.length > 0 && <DraftBlockReasons issues={savedIssues} label={`${name}, ${range(block)}`} descriptionId={`${blockId}-reasons`} suppressed={!!editing.move} />
            const request = indicator && <RequestDetails className={`request-indicator ${indicator.status}`} name={name} rows={[indicator]} hint={`${indicator.status === 'met' ? 'Request met' : 'Request not met'} - click for details`}><RequestIndicatorIcon status={indicator.status} /></RequestDetails>
            const blockLabel = `${name} - ${range(block)} - ${draftPrefix}${value}${classification}${qualifiers.length ? ` - ${qualifiers.join(', ')}` : ''}`
            const makeBlock = (anchor: HTMLButtonElement): DraftBlock => ({ ...cell, name, label: value, id: blockId, anchor })
            if (start) return <td key={block[0].month} colSpan={block.length} className="draft-block-slot"
              onDragOver={(event) => dragOver(event, cell)} onDrop={(event) => dropOnCell(event, cell)}>
              <div className={`draft-posting-cell${issueStyle ? ` ${issueStyle}` : ''}${picked ? ' picked' : ''}${aimed ? ' aimed' : ''}${swapping ? ' swap-target' : ''}`}>
                <button type="button" id={blockId} className={`posting-value ${category} draft-block-button`} aria-label={blockLabel}
                  aria-describedby={warning ? `${blockId}-reasons` : undefined} aria-busy={aimed && editing.checking ? true : undefined}
                  aria-haspopup="dialog" disabled={!canEdit}
                  data-posting-tooltip={`${hoverName} · ${hoverRange}`} data-draft-start={start} draggable={canEdit}
                  onClick={(event) => editing.openEditor(makeBlock(event.currentTarget))}
                  onKeyDown={(event) => keyboardMove(event, makeBlock(event.currentTarget), draftMonths)}
                  onDragStart={(event) => {
                    event.dataTransfer.effectAllowed = 'move'
                    event.dataTransfer.setData('text/plain', blockId)
                    editing.startMove(makeBlock(event.currentTarget), false)
                  }} onDragEnd={editing.finishDrag}>
                  <span className="posting-name">{value}</span>
                </button>
                {request}{warning}
              </div>
              {held && draftMonths[previewAnchor]?.month === block[0].month &&
                <DraftInsertionPreview months={draftMonths} preview={insertion?.changed ? insertion.blocks : null} held={held.start}
                  anchorIndex={previewAnchor} anchorLength={block.length} source={resident.source} warnings={draft?.edit_warnings ?? []} requestIndicator={requestIndicator} />}
            </td>
            return <td key={block[0].month} colSpan={block.length}
              onDragOver={(event) => dragOver(event, cell)} onDrop={(event) => dropOnCell(event, cell)}
              className={issueStyle ? `draft-static-destination ${issueStyle}` : undefined}><div className={`posting-value ${category}`} role="group"
              data-posting-tooltip={`${projection}${hoverName} • ${hoverRange}`} aria-describedby={warning ? `${blockId}-reasons` : undefined}
              aria-label={`${show(resident.name)} - ${range(block)} - ${draftPrefix}${value}${classification}${qualifiers.length ? ` - ${qualifiers.join(', ')}` : ''}`}>
              <span className="posting-name">{value}</span>
              {request}{warning}
              {qualifiers.length > 0 && <span className="posting-markers">{qualifiers.map((marker) => <span className={`posting-marker${marker === 'Remediation' ? ' posting-marker-remediation' : ''}`} key={marker}>{marker}</span>)}</span>}
            </div></td>
          })}
        </tr>
      })}</tbody>
    </table></TimetableGrid>}
    </div>
    {editing.released && <DraftMoveFeedback anchor={editing.released.anchor} kind={editing.released.kind} checking={editing.checking} preview={editing.preview}
      onApply={editing.confirmDrop} onDismiss={() => editing.dismissDrop()} />}
    {editor && draft && editorResident && <DraftBlockEditor block={editor} options={draft.edit_options ?? []} current={editorCurrent}
      years={`${editorResident.recorded_year ?? ''};${editorResident.projected_year ?? ''};${workbook.residents.find((person) => sameSource(person.source, editor.source))?.residency_year ?? ''}`}
      checking={editing.checking} canApply={!!editing.preview?.draft} issues={editing.preview?.issues ?? []}
      onSelect={(option) => option ? editing.check({ kind: 'edit', resident: editor.source, start: editor.start,
        posting: option.posting, institution: option.institution, offering: option.source }, [editor]) : editing.clearPreview()}
      onApply={() => void editing.apply(editor)} onClose={editing.closeEditor} />}
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
  const workbookYears = useRef(new Map<number, Workbook>())
  const yearRequests = useRef(new Map<number, { controller: AbortController; result: Promise<Workbook> }>())
  const warmAfterPaint = useRef(false)
  const timetableLabels = useRef(new Map<Workbook, TimetableLabels>())
  const [selectedLabels, setSelectedLabels] = useState<TimetableLabels>()
  const saveLabels = useCallback((result: Workbook, labels: TimetableLabels) => {
    if (currentSession.current?.workbook === result) {
      timetableLabels.current.set(result, labels)
      setSelectedLabels(labels)
    }
  }, [])
  const clearYearCache = useCallback(() => {
    for (const { controller } of yearRequests.current.values()) controller.abort()
    yearRequests.current.clear()
    workbookYears.current.clear()
    timetableLabels.current.clear()
    warmAfterPaint.current = false
  }, [])
  const activeImport = useRef<AbortController | null>(null)
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
      workbookYears.current.set(saved.workbook.target_year, saved.workbook)
      warmAfterPaint.current = true
      revealAfterUpload.current = saved.workbook.residents.length > 0
      setFile(saved.file); setWorkbook(saved.workbook); setYear(saved.workbook.target_year)
      if (saved.draft) restoreDraft(saved.draft)
    }).catch((problem: unknown) => {
      if (!cancelled) setStorageError(problem instanceof Error ? problem.message : 'The saved workbook could not be restored.')
    }).finally(() => { if (!cancelled) setRestoring(false) })
    return () => { cancelled = true }
  }, [restoreDraft])
  useEffect(() => () => { activeImport.current?.abort(); clearYearCache() }, [clearYearCache])
  useEffect(() => {
    if (!restoring && currentSession.current) persistCurrent()
  }, [file, workbook, draftMemory.savedResult, restoring, persistCurrent])
  const hasDraft = isUsableDraft(draftState.draft)
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

  const prepareCachedYear = useCallback((session: { file: File; workbook: Workbook }, nextYear: number) => {
    const cached = workbookYears.current.get(nextYear)
    if (cached) return Promise.resolve(cached)
    const pending = yearRequests.current.get(nextYear)
    if (pending) return pending.result
    const controller = new AbortController()
    const raw = reviewSnapshot()
    const reviews = readTimetableReviews(raw)
    const result = prepareYear(session.workbook, nextYear, reviews.store, controller.signal).then(({ workbook, labels }) => {
      controller.signal.throwIfAborted()
      workbookYears.current.set(nextYear, workbook)
      if (!reviews.error && reviewSnapshot() === raw) {
        timetableLabels.current.set(workbook, { signature: reviews.signature, data: labels })
      }
      return workbook
    }).finally(() => {
      if (yearRequests.current.get(nextYear)?.controller === controller) yearRequests.current.delete(nextYear)
    })
    yearRequests.current.set(nextYear, { controller, result })
    return result
  }, [])

  const revealTimetable = useCallback((target: HTMLElement, result: Workbook, labelsReady: boolean) => {
    const session = currentSession.current
    let cancelWarm: (() => void) | undefined
    if (labelsReady && warmAfterPaint.current && !activeImport.current && session?.workbook === result) {
      const warm = () => {
        if (!warmAfterPaint.current || activeImport.current || currentSession.current !== session) return
        warmAfterPaint.current = false
        const previous = result.available_years.reduce((year, item) =>
          item.year < result.target_year && (year === undefined || item.year > year) ? item.year : year, undefined as number | undefined)
        if (previous !== undefined && result.annual_sheets?.length) {
          void prepareCachedYear(session, previous).catch(() => {})
        }
      }
      if (typeof window.requestIdleCallback === 'function') {
        const idle = window.requestIdleCallback(warm, { timeout: 150 })
        cancelWarm = () => window.cancelIdleCallback(idle)
      } else {
        const timer = window.setTimeout(warm, 50)
        cancelWarm = () => window.clearTimeout(timer)
      }
    }
    let cancelScroll: (() => void) | undefined
    if (revealAfterUpload.current) {
      revealAfterUpload.current = false
      const card = review.current || target
      cancelScroll = scrollToPosition(window.scrollY + card.getBoundingClientRect().top - 16)
    }
    return () => { cancelWarm?.(); cancelScroll?.() }
  }, [prepareCachedYear])

  function selectWorkbook(nextFile: File, result: Workbook) {
    currentSession.current = { file: nextFile, workbook: result }
    workbookYears.current.set(result.target_year, result)
    setSelectedLabels(timetableLabels.current.get(result))
    setWorkbook(result); setFile(nextFile); setYear(result.target_year)
  }
  async function load(nextFile: File, nextYear?: number, reveal = false) {
    if (activeImport.current) return
    const controller = new AbortController()
    activeImport.current = controller
    setLoadingHeight(review.current?.getBoundingClientRect().height)
    setBusy(true); setError(''); setStatus(''); setFocusSource(null)
    try {
      const session = currentSession.current
      const result = nextYear !== undefined && session?.file === nextFile && session.workbook.annual_sheets?.length
        ? await prepareCachedYear(session, nextYear)
        : await importWorkbook(nextFile, nextYear, controller.signal)
      if (controller.signal.aborted) return
      revealAfterUpload.current = reveal
      if (reveal) {
        clearYearCache()
        warmAfterPaint.current = true
        draftMemory.discard(); setView('Timetable'); setQuery('')
      }
      selectWorkbook(nextFile, result)
    } catch (problem: unknown) {
      if (controller.signal.aborted) return
      setYear(workbook?.target_year ?? year)
      setError(problem instanceof Error ? problem.message : 'Workbook import failed. Please try again.')
      setStatus(file ? 'The previous import is still available.' : '')
    } finally {
      if (activeImport.current === controller) activeImport.current = null
      if (!controller.signal.aborted) setBusy(false)
    }
  }
  function choose(files: File[]) {
    if (busy || restoring || !files.length) return
    const problem = workbookError(files)
    if (problem) { setError(problem); return }
    void load(files[0], undefined, true)
  }
  function selectYear(nextYear: number) {
    if (!file || activeImport.current || busy || restoring) return
    warmAfterPaint.current = false
    const cached = currentSession.current?.file === file ? workbookYears.current.get(nextYear) : undefined
    if (cached) {
      setError(''); setStatus(''); setFocusSource(null)
      selectWorkbook(file, cached)
    } else {
      setYear(nextYear); void load(file, nextYear)
    }
  }
  function removeWorkbook() {
    currentSession.current = null
    clearYearCache()
    setSelectedLabels(undefined)
    discardSavedDraft()
    setFile(null); setWorkbook(null); setYear(undefined); setError(''); setQuery('')
    setStatus('Import removed. Choose or drop another workbook.')
    browse.current?.focus()
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
          <div className="upload-actions"><input ref={input} type="file" accept=".xlsx" hidden disabled={busy || restoring} aria-label="Programme workbook" onChange={(event) => { choose(Array.from(event.target.files || [])); event.target.value = '' }} /><button ref={browse} className="button" type="button" disabled={busy || restoring} aria-describedby={error ? 'import-error' : undefined} onClick={() => input.current?.click()}>{restoring ? 'Restoring workbook...' : busy ? 'Reading workbook…' : file ? 'Replace workbook' : 'Choose workbook'}</button>{file && <button className="button button-secondary" type="button" disabled={busy} onClick={removeWorkbook}>Remove</button>}</div>
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
          onYearChange={selectYear} draftState={draftState} breakdownHost={breakdownHost} onReady={revealTimetable} importLoading={busy || restoring} exporting={exporting}
          labels={selectedLabels} onLabels={saveLabels}
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
