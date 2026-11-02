import { useRef, useState } from 'react'
import ConnectionStatus from './components/ConnectionStatus'
import Skeleton from './components/Skeleton'
import { importWorkbook, monthLabel, sourceLabel, workbookError } from './lib/workbook'
import type { Resident, Source, Workbook } from './lib/workbook'

type View = 'Timetable' | 'Residents' | 'Requests' | 'Postings' | 'Issues'
const views: View[] = ['Timetable', 'Residents', 'Requests', 'Postings', 'Issues']
const show = (value: string | null | undefined) => value || '—'
const source = (value: Source) => <small className="source">{sourceLabel(value)}</small>
const linked = (a: Source, b: Source | null | undefined) => a.sheet === b?.sheet && a.row === b?.row

function ResidentDetail({ resident, workbook }: { resident: Resident; workbook: Workbook }) {
  const requests = workbook.requests.filter((request) => linked(resident.source, request.matched_resident_source))
  const histories = workbook.histories.map((history) => ({ ...history, residents: history.residents.filter((person) => linked(resident.source, person.matched_resident_source)) })).filter((history) => history.residents.length)
  return <details className="resident-detail">
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
      <h3>Recorded history</h3>
      <p className="muted">Workbook records only. These entries do not establish credited or completed training. Unresolved identity matches appear in Issues.</p>
      {histories.length ? histories.map((history) => <div className="history-year" key={history.sheet}>
        <h4>{history.year}–{history.year + 1}</h4>
        {history.residents.map((person, index) => <div key={index}>{source(person.source)}<div className="history-months">{person.postings.map((posting) => <div key={posting.month}><span>{monthLabel(posting.month)}</span><p>{posting.value || 'No entry'}</p>{source(posting.source)}</div>)}</div>{person.remarks && <p className="record-note">{person.remarks}</p>}</div>)}
      </div>) : <p className="muted">No safely matched historical records in this workbook.</p>}
    </div>
  </details>
}

function Review({ workbook, view, query }: { workbook: Workbook; view: View; query: string }) {
  const matches = (name: string | null, mcr: string | null) => `${name || ''} ${mcr || ''}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
  const residents = workbook.residents.filter((resident) => matches(resident.name, resident.mcr))
  if (view === 'Issues') return <div className="review-content"><h2>Import issues</h2>
    {workbook.issues?.length || workbook.warnings.length ? <ul className="issue-list">{workbook.issues?.map((issue, index) => <li key={`issue-${index}`}><p>{issue.severity === 'info' ? 'Information: ' : 'Review: '}{issue.message}</p>{source(issue.source)}{issue.values && <details><summary>View recorded posting values</summary>{issue.values.map((value, valueIndex) => <div className="record" key={valueIndex}><p>{value}</p>{issue.sources?.[valueIndex] && source(issue.sources[valueIndex])}</div>)}</details>}</li>)}{workbook.warnings.map((warning, index) => <li key={`warning-${index}`}>{warning}</li>)}</ul> : <p className="muted">No import issues were reported. Imported records still need programme review.</p>}
    <details className="raw-postings"><summary>Review unresolved historical rows</summary>{workbook.histories.map((history) => <div key={history.sheet}>{history.residents.filter((person) => person.match_status !== 'matched').map((person, index) => <div className="record" key={index}><p>{show(person.name)} · {show(person.mcr)} · {person.match_status || 'Unresolved'}</p>{source(person.source)}<p>{person.postings.map((posting) => `${monthLabel(posting.month)}: ${posting.value || 'No entry'}`).join(' · ')}</p></div>)}</div>)}</details>
  </div>
  if (view === 'Postings') return <div className="review-content"><h2>Posting reference</h2><p className="muted">Reference values recorded in the workbook. Blank capacity means unknown.</p>
    {workbook.postings.core.length ? <div className="table-scroll"><table><caption className="sr-only">Core posting reference</caption><thead><tr><th>Residency year</th><th>Posting</th><th>Duration (months)</th><th>Maximum</th><th>Remarks / source</th></tr></thead><tbody>{workbook.postings.core.map((posting, index) => <tr key={index}><td>{show(posting.residency_year)}</td><td>{show(posting.posting)}</td><td>{show(posting.duration_months)}</td><td>{show(posting.max)}</td><td>{show(posting.remarks)}{source(posting.source)}</td></tr>)}</tbody></table></div> : <p className="empty-note">No core posting reference was found.</p>}
    <details className="raw-postings"><summary>View all posting reference rows</summary><div className="table-scroll"><table><caption className="sr-only">Raw posting reference rows, with original column letters</caption><thead><tr><th>Source</th><th>Recorded cells</th></tr></thead><tbody>{workbook.postings.rows.map((row, index) => <tr key={index}><td>{source(row.source)}</td><td>{Object.entries(row.cells).map(([column, value]) => <span className="raw-cell" key={column}><strong>{column}</strong> {show(value)}</span>)}</td></tr>)}</tbody></table></div></details>
  </div>
  if (view === 'Requests') {
    const requests = workbook.requests.filter((request) => matches(request.name, request.mcr))
    return requests.length ? <div className="table-scroll"><table><caption className="sr-only">Workbook posting requests</caption><thead><tr><th>Resident</th><th>Request</th><th>Period</th><th>Remarks / source</th></tr></thead><tbody>{requests.map((request, index) => <tr key={index}><th scope="row">{show(request.name)}<small>{show(request.mcr)}</small></th><td>{show(request.posting_request)}</td><td>{show(request.period)}</td><td>{show(request.remarks)}{source(request.source)}<small>Identity: {request.match_status || 'Unresolved'}</small></td></tr>)}</tbody></table></div> : <p className="empty-note">No requests match this search.</p>
  }
  if (!residents.length) return <p className="empty-note">{workbook.residents.length ? 'No residents match this search.' : 'No resident rows were found for this planning year.'}</p>
  if (view === 'Residents') return <div className="resident-list">{residents.map((resident, index) => <ResidentDetail key={index} resident={resident} workbook={workbook} />)}</div>
  return <><div className="table-scroll timetable"><table><caption className="sr-only">Imported timetable for July {workbook.target_year} to June {workbook.target_year + 1}. Blank cells are labelled unallocated.</caption><thead><tr><th scope="col">Resident</th>{workbook.months.map((month) => <th scope="col" key={month.month} title={sourceLabel(month.source)}>{monthLabel(month.month)}</th>)}</tr></thead><tbody>{residents.map((resident, index) => <tr key={index}><th scope="row"><span>{show(resident.name)}</span><small>{show(resident.residency_year)} · {show(resident.mcr)}</small></th>{resident.postings.map((posting) => <td key={posting.month}><span className={posting.value ? 'posting-value' : 'posting-value unallocated'} title={sourceLabel(posting.source)}>{posting.value || 'Unallocated'}</span></td>)}</tr>)}</tbody></table></div><p className="table-note">Imported workbook entries. Open Residents to review source rows, linked requests and recorded history.</p></>
}

export default function App() {
  const input = useRef<HTMLInputElement>(null)
  const browse = useRef<HTMLButtonElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [workbook, setWorkbook] = useState<Workbook | null>(null)
  const [year, setYear] = useState(2027)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('')
  const [dragging, setDragging] = useState(false)
  const [view, setView] = useState<View>('Timetable')
  const [query, setQuery] = useState('')

  async function load(nextFile: File, nextYear: number) {
    setBusy(true); setError(''); setStatus(`Reading ${nextFile.name}…`)
    try {
      const result = await importWorkbook(nextFile, nextYear)
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
    void load(files[0], year)
  }
  const years = [...new Set([2027, year, ...(workbook?.available_years.map((item) => item.year) || [])])].sort((a, b) => b - a)
  const issueCount = workbook ? (workbook.issues?.length || 0) + workbook.warnings.length : 0
  return <>
    <a href="#main" className="skip-link">Skip to workspace</a>
    <header className="site-header"><a href="/" className="brand" aria-label="PSY Residency Scheduler home"><span className="brand-mark" aria-hidden="true">PSY</span><span>Residency scheduler</span></a><span className="workspace-label">Local workspace</span></header>
    <main id="main" className="site-main" tabIndex={-1}>
      <div className="page-heading"><h1>Posting timetable</h1><p>NHG Psychiatry Residency Programme</p></div>
      <section className="workspace-panel" aria-labelledby="import-title">
        <div className="panel-heading"><h2 id="import-title">Workbook import</h2><span className="badge">Current session only</span></div>
        <div className={`workbook-chooser ${dragging ? 'is-dragging' : ''}`} onDragOver={(event) => { event.preventDefault(); if (!busy) setDragging(true) }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node)) setDragging(false) }} onDrop={(event) => { event.preventDefault(); setDragging(false); choose(Array.from(event.dataTransfer.files)) }}>
          <div className="upload-copy">{file ? <><h3 className="filename">{file.name}</h3><p>{file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / 1024 / 1024).toFixed(1)} MB`} · Imported for {year}–{year + 1}</p></> : <><h3>Start with your programme workbook</h3><p>Choose or drop one .xlsx workbook, up to 10 MB.</p></>}<p className="session-note">Review imported records before planning. Refreshing this page clears the import.</p></div>
          <div className="upload-actions"><input ref={input} type="file" accept=".xlsx" hidden disabled={busy} aria-label="Programme workbook" onChange={(event) => { choose(Array.from(event.target.files || [])); event.target.value = '' }} /><button ref={browse} className="button" type="button" disabled={busy} aria-describedby={error ? 'import-error' : undefined} onClick={() => input.current?.click()}>{busy ? 'Reading workbook…' : file ? 'Replace workbook' : 'Choose workbook'}</button>{file && <button className="button button-secondary" type="button" disabled={busy} onClick={() => { setFile(null); setWorkbook(null); setError(''); setQuery(''); setStatus('Import removed. Choose or drop another workbook.'); browse.current?.focus(); }}>Remove</button>}</div>
        </div>
        <div className="import-feedback"><p role="status" aria-live="polite">{status}</p>{error && <p id="import-error" role="alert" className="error-message">{error}{workbook && ' Your previous import is unchanged.'}</p>}</div>
      </section>
      {(workbook || busy) && <section className="workspace-panel review-panel" aria-label="Workbook review" aria-busy={busy}>
        <div className="review-toolbar"><label>Planning year<select value={year} disabled={busy} onChange={(event) => { if (file) void load(file, Number(event.target.value)) }}>{years.map((value) => <option key={value} value={value}>Jul {value} – Jun {value + 1}</option>)}</select></label>{workbook && <p className="sheet-label">Source: {workbook.target_sheet}</p>}</div>
        <nav className="view-nav" aria-label="Workbook views">{views.map((item) => <button type="button" key={item} className={view === item ? 'active' : ''} aria-current={view === item ? 'page' : undefined} disabled={busy} onClick={() => setView(item)}>{item}{item === 'Issues' && issueCount ? ` (${issueCount})` : ''}</button>)}</nav>
        {busy ? <div className="loading-region"><p>Reading workbook sheets and linking resident records…</p><Skeleton /></div> : workbook && <>{['Timetable', 'Residents', 'Requests'].includes(view) && <div className="search-toolbar"><label htmlFor="resident-search">Search residents</label><input id="resident-search" type="search" placeholder="Name or MCR number" value={query} onChange={(event) => setQuery(event.target.value)} /></div>}<Review workbook={workbook} view={view} query={query} /></>}
      </section>}
      <div className="connection-container"><ConnectionStatus /></div>
    </main>
  </>
}
