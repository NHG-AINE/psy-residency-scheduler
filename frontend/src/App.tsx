import { useEffect, useRef, useState } from 'react'
import Skeleton from './components/Skeleton'
import ResidentRequirements from './components/ResidentRequirements'
import ImportIssues from './components/ImportIssues'
import PostingReference from './components/PostingReference'
import HistoricalPostingReview from './components/HistoricalPostingReview'
import SearchField from './components/SearchField'
import { importWorkbook, monthLabel, sourceLabel, workbookError } from './lib/workbook'
import type { Resident, Source, Workbook } from './lib/workbook'
import { groupPostings, postingCategory, postingDisplay } from './lib/posting-blocks'
import { evaluateHistory, readReviewStore, STORAGE_KEY } from './lib/history-review'
import type { HistoryReview } from './lib/history-review'
import type { PostingBlock } from './lib/posting-blocks'

type View = 'Timetable' | 'Residents' | 'Requests' | 'Postings' | 'History review' | 'Issues'
const views: View[] = ['Timetable', 'Residents', 'Requests', 'Postings', 'History review', 'Issues']
const show = (value: string | null | undefined) => value || '—'
const source = (value: Source) => <small className="source">{sourceLabel(value)}</small>
const linked = (a: Source, b: Source | null | undefined) => a.sheet === b?.sheet && a.row === b?.row

function ResidentDetail({ resident, workbook, onHistoryReview }: { resident: Resident; workbook: Workbook; onHistoryReview: () => void }) {
  const [tab, setTab] = useState('history')
  const [open, setOpen] = useState(false)
  const requests = workbook.requests.filter((request) => request.posting_request?.trim() && linked(resident.source, request.matched_resident_source))
  const histories = workbook.histories.map((history) => ({ ...history, residents: history.residents.filter((person) => linked(resident.source, person.matched_resident_source)) })).filter((history) => history.residents.length)
  return <details className="resident-detail" onToggle={(event) => setOpen(event.currentTarget.open)}>
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

function Review({ workbook, view, query, year, years, onYearChange, onHistoryReview, historyResident, loading = false }: { workbook: Workbook; view: View; query: string; year: number; years: number[]; onYearChange: (year: number) => void; onHistoryReview: (resident: Resident) => void; historyResident: string; loading?: boolean }) {
  const matches = (name: string | null, mcr: string | null) => `${name || ''} ${mcr || ''}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
  const residents = workbook.residents.filter((resident) => matches(resident.name, resident.mcr))
  if (view === 'Issues') return <div className="review-content"><h2 className="issues-heading">Import issues <span className={`badge issue-badge ${(workbook.issues?.length || 0) + workbook.warnings.length > 0 ? 'issue-badge-warning' : 'issue-badge-neutral'}`} aria-label={`${(workbook.issues?.length || 0) + workbook.warnings.length} import issues`}>{(workbook.issues?.length || 0) + workbook.warnings.length}</span></h2>
    <ImportIssues issues={workbook.issues || []} warnings={workbook.warnings} />
  </div>
  if (view === 'History review') return <HistoricalPostingReview workbook={workbook} initialQuery={historyResident} />
  if (view === 'Postings') return <PostingReference workbook={workbook} />
  if (view === 'Requests') {
    const requests = workbook.requests.filter((request) => request.posting_request?.trim() && matches(request.name, request.mcr))
    return <><p className="table-note">Requests are not assigned to a planning year. The selected year changes resident links, not request dates or the recorded request rows.</p>{requests.length ? <div className="table-scroll"><table><caption className="sr-only">Workbook posting requests</caption><thead><tr><th>Resident</th><th>Request</th><th>Period</th><th>Remarks / source</th></tr></thead><tbody>{requests.map((request, index) => <tr key={index}><th scope="row">{show(request.name)}<small>{show(request.mcr)}</small></th><td>{show(request.posting_request)}</td><td>{show(request.period)}</td><td>{show(request.remarks)}{source(request.source)}<small>Identity: {request.match_status || 'Unresolved'}</small></td></tr>)}</tbody></table></div> : <p className="empty-note">No requests match this search.</p>}</>
  }
  if (view === 'Timetable') return <Timetable residents={residents} workbook={workbook} year={year} years={years} onYearChange={onYearChange} importLoading={loading} />
  if (!residents.length) return <p className="empty-note">{workbook.residents.length ? 'No residents match this search.' : 'No resident rows were found for this planning year.'}</p>
  return <div className="resident-list">{residents.map((resident, index) => <ResidentDetail key={index} resident={resident} workbook={workbook} onHistoryReview={() => onHistoryReview(resident)} />)}</div>
}

const postingCategoryLabels = { core: 'Core', elective: 'Elective', loa: 'LOA', unresolved: 'Unresolved', unallocated: 'Unallocated' }

function Timetable({ residents, workbook, year, years, onYearChange, importLoading = false }: { residents: Resident[]; workbook: Workbook; year: number; years: number[]; onYearChange: (year: number) => void; importLoading?: boolean }) {
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
  const availableYears = [...years].sort((a, b) => a - b)
  const yearIndex = availableYears.indexOf(year)
  const words = (value: string) => value.split(/(\s+)/).map((word, index) => /\s/.test(word) ? word : <span className="posting-word" key={index}>{word}</span>)
  const range = (block: PostingBlock) => block.length === 1 ? monthLabel(block[0].month) : `${monthLabel(block[0].month)} – ${monthLabel(block[block.length - 1].month)}`
  return <>
    <div className="timetable-toolbar"><div className="year-navigation" role="group" aria-label="Timetable planning year"><button type="button" className="button button-secondary year-arrow" aria-label="Previous planning year" disabled={importLoading || yearIndex <= 0} onClick={() => onYearChange(availableYears[yearIndex - 1])}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m10 3-5 5 5 5" /></svg></button><span className="year-range">Jul {year} - Jun {year + 1}</span><button type="button" className="button button-secondary year-arrow" aria-label="Next planning year" disabled={importLoading || yearIndex < 0 || yearIndex >= availableYears.length - 1} onClick={() => onYearChange(availableYears[yearIndex + 1])}><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3 5 5-5 5" /></svg></button></div><ul className="posting-legend" aria-label="Posting colour legend">{Object.entries(postingCategoryLabels).map(([kind, label]) => <li key={kind}><span aria-hidden="true" className={`legend-dot legend-${kind}`} />{label}</li>)}</ul></div>
    {error && <div className="timetable-label-error" role="alert"><p>Catalogue labels are unavailable. Original labels are shown. {error}</p><button className="button button-secondary" type="button" onClick={() => setAttempt((value) => value + 1)}>Retry catalogue labels</button></div>}
    <div aria-busy={loading}>
    {loading ? <><span className="sr-only" role="status">{importLoading ? 'Loading workbook data' : 'Loading catalogue labels'}</span><Skeleton /></> : !residents.length ? <p className="empty-note">{workbook.residents.length ? 'No residents match this search.' : 'No resident rows were found for this planning year.'}</p> : <div className="table-scroll timetable"><table>
      <caption className="sr-only">Imported timetable for July {workbook.target_year} to June {workbook.target_year + 1}. Blank cells are labelled unallocated.</caption>
      <colgroup><col className="resident-column" />{workbook.months.map((month) => <col key={month.month} />)}</colgroup>
      <thead><tr><th scope="col">Resident</th>{workbook.months.map((month) => <th scope="col" key={month.month} title={sourceLabel(month.source)}>{monthLabel(month.month)}</th>)}</tr></thead>
      <tbody>{residents.map((resident, index) => <tr key={index}>
        <th scope="row"><span>{words(show(resident.name))}</span><small>{words(`${show(resident.mcr)} · ${show(resident.residency_year)}`)}</small></th>
        {groupPostings(resident.postings).map((block) => {
          const status = block[0].status
          const display = postingDisplay(block, 'catalogue', resolution?.entries)
          const value = display.label
          const category = postingCategory(display, status)
          const classification = ` - ${postingCategoryLabels[category]}`
          const qualifiers = display.markers.filter((marker) => marker !== 'Elective')
          const hoverName = category === 'elective' && !/\(\s*elective\s*\)/i.test(value) ? `${value} (Elective)` : value
          const hoverRange = range(block).replaceAll('Sept ', 'Sep ').replace('–', '-')
          return <td key={block[0].month} colSpan={block.length}><div
            className={`posting-value ${category}`}
            title={`${hoverName} • ${hoverRange}`} aria-label={`${show(resident.name)} - ${range(block)} - ${value}${classification}${qualifiers.length ? ` - ${qualifiers.join(', ')}` : ''}`}
            >
            {words(value)}
            {display.markers.some((marker) => marker !== 'Elective') && <span className="posting-markers">{display.markers.filter((marker) => marker !== 'Elective').map((marker) => <span className={`posting-marker${marker === 'Remediation' ? ' posting-marker-remediation' : ''}`} key={marker}>{marker}</span>)}</span>}
          </div></td>
        })}
      </tr>)}</tbody>
    </table></div>}
    </div>
  </>
}

export default function App() {
  const input = useRef<HTMLInputElement>(null)
  const browse = useRef<HTMLButtonElement>(null)
  const review = useRef<HTMLElement>(null)
  const revealAfterUpload = useRef(false)
  const [file, setFile] = useState<File | null>(null)
  const [workbook, setWorkbook] = useState<Workbook | null>(null)
  const [year, setYear] = useState(2027)
  const [busy, setBusy] = useState(false)
  const [loadingHeight, setLoadingHeight] = useState<number>()
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [dragging, setDragging] = useState(false)
  const [view, setView] = useState<View>('Timetable')
  const [query, setQuery] = useState('')
  const [historyResident, setHistoryResident] = useState('')

  useEffect(() => {
    if (busy || !workbook || !revealAfterUpload.current) return
    revealAfterUpload.current = false
    const target = review.current?.querySelector<HTMLElement>('.timetable') || review.current
    if (!target) return
    const rect = target.getBoundingClientRect()
    const start = window.scrollY
    const offset = rect.height > window.innerHeight - 32 ? 16 : (window.innerHeight - rect.height) / 2
    const end = Math.max(0, Math.min(start + rect.top - offset, document.documentElement.scrollHeight - window.innerHeight))
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      window.scrollTo({ top: end, behavior: 'instant' })
      return
    }
    const started = performance.now()
    let frame = 0
    const cancel = () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('wheel', cancel)
      window.removeEventListener('touchstart', cancel)
      window.removeEventListener('keydown', cancel)
    }
    const animate = (now: number) => {
      const progress = Math.min((now - started) / 700, 1)
      const eased = progress < 0.5 ? 4 * progress ** 3 : 1 - (-2 * progress + 2) ** 3 / 2
      window.scrollTo({ top: start + (end - start) * eased, behavior: 'instant' })
      if (progress < 1) frame = requestAnimationFrame(animate)
      else cancel()
    }
    window.addEventListener('wheel', cancel, { passive: true })
    window.addEventListener('touchstart', cancel, { passive: true })
    window.addEventListener('keydown', cancel)
    frame = requestAnimationFrame(animate)
    return cancel
  }, [busy, workbook])

  async function load(nextFile: File, nextYear: number, reveal = false) {
    setLoadingHeight(review.current?.getBoundingClientRect().height)
    setBusy(true); setError(''); setStatus(`Reading ${nextFile.name}…`)
    try {
      const result = await importWorkbook(nextFile, nextYear)
      revealAfterUpload.current = reveal
      if (reveal) setView('Timetable')
      setWorkbook(result); setFile(nextFile); setYear(result.target_year); setQuery('')
      setStatus(`Imported ${nextFile.name}. ${result.residents.length} residents in the selected planning year. ${(result.issues?.length || 0) + result.warnings.length} import issues.`)
    } catch (problem: unknown) {
      setError(problem instanceof Error ? problem.message : 'Workbook import failed. Please try again.')
      setStatus(file ? 'The previous import is still available.' : '')
    } finally { setBusy(false) }
  }
  function choose(files: File[]) {
    if (busy || !files.length) return
    const problem = workbookError(files)
    if (problem) { setError(problem); return }
    void load(files[0], year, true)
  }
  function selectYear(nextYear: number) {
    if (file && !busy) void load(file, nextYear)
  }
  const years = [...new Set(workbook?.available_years.map((item) => item.year) || [year])].sort((a, b) => b - a)
  const issueCount = workbook ? (workbook.issues?.length || 0) + workbook.warnings.length : 0
  return <>
    <a href="#main" className="skip-link">Skip to workspace</a>
    <header className="site-header"><a href="/" className="brand" aria-label="PSY Residency Scheduler home"><span className="brand-mark" aria-hidden="true">PSY</span><span>Residency scheduler</span></a></header>
    <main id="main" className="site-main" tabIndex={-1}>
      <div className="page-heading"><h1>Posting timetable</h1><p>NHG Psychiatry Residency Programme</p></div>
      <section className="workspace-panel" aria-labelledby="import-title">
        <div className="panel-heading"><h2 id="import-title">Workbook import</h2><span className="badge">Current session only</span></div>
        <div className={`workbook-chooser ${dragging ? 'is-dragging' : ''}`} onDragOver={(event) => { event.preventDefault(); if (!busy) setDragging(true) }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false) }} onDrop={(event) => { event.preventDefault(); setDragging(false); choose(Array.from(event.dataTransfer.files)) }}>
          <div className="upload-copy">{file ? <><h3 className="filename">{file.name}</h3><p>{file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / 1024 / 1024).toFixed(1)} MB`} · Imported for {year}–{year + 1}</p></> : <><h3>Start with your programme workbook</h3><p>Choose or drop one .xlsx workbook, up to 10 MB.</p></>}<p className="session-note">Review imported records before planning. Refreshing this page clears the import. Historical review decisions are saved separately in this browser.</p></div>
          <div className="upload-actions"><input ref={input} type="file" accept=".xlsx" hidden disabled={busy} aria-label="Programme workbook" onChange={(event) => { choose(Array.from(event.target.files || [])); event.target.value = '' }} /><button ref={browse} className="button" type="button" disabled={busy} aria-describedby={error ? 'import-error' : undefined} onClick={() => input.current?.click()}>{busy ? 'Reading workbook…' : file ? 'Replace workbook' : 'Choose workbook'}</button>{file && <button className="button button-secondary" type="button" disabled={busy} onClick={() => { setFile(null); setWorkbook(null); setError(''); setQuery(''); setStatus('Import removed. Choose or drop another workbook.'); browse.current?.focus(); }}>Remove</button>}</div>
        </div>
        <div className="import-feedback"><p role="status" aria-live="polite">{status}</p>{error && <p id="import-error" role="alert" className="error-message">{error}{workbook && ' Your previous import is unchanged.'}</p>}</div>
      </section>
      {(workbook || busy) && <section ref={review} style={{ minHeight: busy ? loadingHeight : undefined }} className="workspace-panel review-panel" aria-label="Workbook review" aria-busy={busy}>
        <nav className="view-nav" aria-label="Workbook views">{views.map((item) => <button type="button" key={item} className={view === item ? 'active' : ''} aria-current={view === item ? 'page' : undefined} disabled={busy} onClick={() => { setHistoryResident(''); setView(item) }}>{item}{item === 'Issues' && issueCount ? ` (${issueCount})` : ''}</button>)}</nav>
        {['Timetable', 'Residents', 'Requests'].includes(view) && <div className="search-toolbar">{view !== 'Timetable' && <label>Planning year<select value={year} disabled={busy} onChange={(event) => selectYear(Number(event.target.value))}>{years.map((value) => <option key={value} value={value}>Jul {value} - Jun {value + 1}</option>)}</select></label>}<SearchField id="resident-search" label="Search residents" placeholder="Name or MCR number" value={query} disabled={busy} onChange={setQuery} />{workbook && <p className="sheet-label">Source: {workbook.target_sheet}</p>}</div>}
        {workbook && (!busy || view === 'Timetable') ? <Review workbook={workbook} view={view} query={query} year={year} years={years} onYearChange={selectYear} onHistoryReview={(resident) => { setHistoryResident(resident.mcr || resident.name || ''); setView('History review') }} historyResident={historyResident} loading={busy} /> : busy && <><span className="sr-only" role="status">Loading workbook data</span><Skeleton /></>}
      </section>}
    </main>
  </>
}
