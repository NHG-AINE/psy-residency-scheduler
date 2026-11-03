import { Fragment, useEffect, useRef, useState } from 'react'
import type { Workbook } from '../lib/workbook'
import { monthLabel, sourceLabel } from '../lib/workbook'
import {
  decisionKey, emptyStore, evaluateHistory, mergeReviewStores, parseReviewStore, readReviewStore,
  reasonLabel, writeReviewStore, historyStatusLabel, matchesHistoryFilter,
} from '../lib/history-review'
import type { CatalogueEntry, HistoryEntry, HistoryReview, ReviewDecision, ReviewStore } from '../lib/history-review'
import SearchField from './SearchField'

const period = (entry: { months: { month: string }[] }) => entry.months.length === 1 ? monthLabel(entry.months[0].month) : `${monthLabel(entry.months[0].month)} – ${monthLabel(entry.months.at(-1)!.month)}`
const targetLabel = (target: CatalogueEntry) => `${target.residency_year || 'Year missing'} · ${target.category === 'core' ? 'Core' : 'Elective'} · ${target.label}`
const errorText = (error: unknown) => error instanceof Error ? error.message : 'History review failed. Please retry.'

function DecisionEditor({ entry, catalogue, store, onSave, onCancel }: {
  entry: HistoryEntry; catalogue: CatalogueEntry[]; store: ReviewStore
  onSave: (decision: ReviewDecision) => void; onCancel: () => void
}) {
  const personal = store.decisions.find((decision) => decision.kind === 'resident' && decisionKey(decision) === entry.key)
  const [scope, setScope] = useState<'resident' | 'alias'>(entry.identity_safe ? 'resident' : 'alias')
  const [targetKey, setTargetKey] = useState(personal?.target.key || entry.review.target?.key || '')
  const [requirementYear, setRequirementYear] = useState(personal?.kind === 'resident' ? personal.requirement_year || '' : '')
  const [search, setSearch] = useState('')
  const choices = catalogue.filter((target) => !entry.match.reasons.includes('explicit_elective') || target.category === 'elective')
  const target = choices.find((candidate) => candidate.key === targetKey)
  const years = target?.residency_year?.toUpperCase().match(/\bR[1-5]\b/g) || []
  const candidates = new Set(entry.match.candidates.map((candidate) => candidate.key))
  const filtered = choices.filter((candidate) => candidate.key === targetKey || targetLabel(candidate).toLowerCase().includes(search.trim().toLowerCase()))
  const context = { label: entry.months[0].value, recorded_year: entry.context.recorded_year, category: target?.category || 'core' as const }
  const decision: ReviewDecision | null = target ? scope === 'resident'
    ? { kind: 'resident', context: entry.context, target: { key: target.key, signature: target.signature }, requirement_year: requirementYear || null }
    : { kind: 'alias', context, target: { key: target.key, signature: target.signature } } : null
  const replacing = decision && store.decisions.some((existing) => decisionKey(existing) === decisionKey(decision))
  return <form className="history-editor" onSubmit={(event) => { event.preventDefault(); if (decision) onSave(decision) }}>
    <div className="history-editor-heading"><h3>Review this posting</h3><button className="button button-secondary" type="button" onClick={onCancel}>Close</button></div>
    <p className="muted">Choose the catalogue label, then confirm its requirement year if known. This does not change the resident’s recorded R-year or award training credit.</p>
    <div className="history-editor-fields">
      <div><SearchField id="history-catalogue-search" label="Find a catalogue entry" placeholder="Institution or posting name" value={search} onChange={setSearch} />
        <label>Catalogue match<select required value={targetKey} onChange={(event) => { setTargetKey(event.target.value); setRequirementYear('') }}><option value="">Choose a catalogue entry</option>
          <optgroup label="Exact catalogue candidates">{filtered.filter((candidate) => candidates.has(candidate.key)).map((candidate, index) => <option key={`${candidate.key}-${index}`} value={candidate.key}>{targetLabel(candidate)}</option>)}</optgroup>
          <optgroup label="Other catalogue entries — manual review">{filtered.filter((candidate) => !candidates.has(candidate.key)).map((candidate, index) => <option key={`${candidate.key}-${index}`} value={candidate.key}>{targetLabel(candidate)}</option>)}</optgroup>
        </select></label>
        {target && <small className="source">{sourceLabel(target.source)}</small>}
      </div>
      <div><label>Apply this label decision to<select value={scope} onChange={(event) => setScope(event.target.value as 'resident' | 'alias')}>
        <option value="resident" disabled={!entry.identity_safe}>This resident and these months</option><option value="alias">Shared label mapping</option>
      </select></label>
        {!entry.identity_safe && <p className="history-help">Resident decisions are unavailable until the identity issues are resolved. A shared mapping confirms wording only.</p>}
        {scope === 'alias' ? <p className="history-help">Shared scope: this original label, recorded R-year “{entry.recorded_year || 'blank'}”, and {target?.category || 'selected'} category. Requirement years must still be reviewed for each resident.</p> : <label>Requirement year — separate confirmation<select value={requirementYear} onChange={(event) => setRequirementYear(event.target.value)}><option value="">Leave unconfirmed</option>{[...new Set(years)].map((year) => <option key={year} value={year}>{year}</option>)}</select></label>}
      </div>
    </div>
    {entry.match.reasons.includes('remediation_credit_review') && <p className="history-warning">Remediation remains subject to separate credit review after confirming the label and year.</p>}
    {replacing && <p className="history-help">Saving replaces the existing decision for this exact scope.</p>}
    <button className="button" type="submit" disabled={!target || (scope === 'resident' && !entry.identity_safe)}>{replacing ? 'Replace saved decision' : 'Save decision'}</button>
  </form>
}

export default function HistoricalPostingReview({ workbook }: { workbook: Workbook }) {
  const [initial] = useState(() => { try { return readReviewStore(window.localStorage) } catch { return { store: emptyStore(), error: 'Browser storage is unavailable. Enable it to save review decisions.' } } })
  const [store, setStore] = useState<ReviewStore>(initial.store)
  const [storageError, setStorageError] = useState(initial.error)
  const [storageBlocked, setStorageBlocked] = useState(!!initial.error)
  const [loaded, setLoaded] = useState<{ workbook: Workbook; store: ReviewStore; retry: number; data: HistoryReview } | null>(null)
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [message, setMessage] = useState('')
  const [retry, setRetry] = useState(0)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('open')
  const [selected, setSelected] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const reviewButton = useRef<HTMLButtonElement | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    void evaluateHistory(workbook, store, controller.signal).then((result) => { if (!controller.signal.aborted) { setLoaded({ workbook, store, retry, data: result }); setError('') } }).catch((problem) => { if (!controller.signal.aborted) setError(errorText(problem)) })
    return () => controller.abort()
  }, [workbook, store, retry])

  const data = loaded?.workbook === workbook && loaded?.store === store && loaded?.retry === retry ? loaded.data : null
  const busy = !data && !error

  function persist(next: ReviewStore): boolean {
    if (storageBlocked) { setStorageError('Resolve the unreadable saved review data below before saving or importing decisions.'); return false }
    setMessage('')
    try {
      writeReviewStore(window.localStorage, next)
      setStore(next); setStorageError(''); setError(''); setMessage('Review decisions saved in this browser.')
      return true
    } catch (problem) { setStorageError(errorText(problem)); return false }
  }
  function save(decision: ReviewDecision) {
    if (persist({ version: 1, decisions: [...store.decisions.filter((existing) => decisionKey(existing) !== decisionKey(decision)), decision] })) { setSelected(null); heading.current?.focus() }
  }
  async function importDecisions(file: File) {
    setActionError(''); setMessage('')
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error('Choose a review JSON file of 10 MB or smaller.')
      persist(mergeReviewStores(store, parseReviewStore(await file.text())))
    } catch (problem) { setActionError(errorText(problem)) }
  }
  function exportDecisions() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(store, null, 2)], { type: 'application/json' }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'historical-posting-review.json'; anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const entries = data?.entries.filter((entry) => matchesHistoryFilter(entry, filter, query)) || []
  const pages = Math.max(1, Math.ceil(entries.length / 25))
  const currentPage = Math.min(page, pages - 1)
  const visible = entries.slice(currentPage * 25, (currentPage + 1) * 25)
  const unapplied = data?.decisions.filter((state) => state.status !== 'applied').length || 0
  return <div className="review-content history-review">
    <div className="history-heading"><div><h2 ref={heading} tabIndex={-1}>Historical posting review</h2><p className="muted">All annual tabs are included, independently of the planning year. Needs review shows unresolved labels. All entries includes recognized labels and their year or credit status. Original records and resident R-years stay intact; no training credit is calculated.</p></div>
      <div className="history-actions"><button className="button button-secondary" type="button" onClick={exportDecisions} disabled={!store.decisions.length}>Export review JSON</button><button className="button button-secondary" type="button" onClick={() => input.current?.click()} disabled={busy || storageBlocked}>Import review JSON</button><input ref={input} type="file" accept=".json,application/json" aria-label="Review JSON file" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void importDecisions(file); event.target.value = '' }} /></div>
    </div>
    <p className="history-help">Decisions are saved in this browser and can be restored after refreshing and re-uploading the workbook. Export a JSON backup to move them to another browser. Workbooks are not saved.</p>
    <p role="status" className="history-feedback">{message}</p>
    {storageError && <div className="history-error" role="alert"><p>{storageError}</p>{storageBlocked ? <button className="button button-secondary" type="button" onClick={() => { setStorageBlocked(false); setStorageError(''); setMessage('Unreadable data will be replaced when you next save a decision.'); }}>Start new review data</button> : <button className="button button-secondary" type="button" onClick={() => setStorageError('')}>Dismiss</button>}</div>}
    {actionError && <div className="history-error" role="alert"><p>{actionError}</p><button className="button button-secondary" type="button" onClick={() => setActionError('')}>Dismiss</button></div>}
    {error && <div className="history-error" role="alert"><p>{error}</p><button className="button button-secondary" type="button" onClick={() => { setError(''); setRetry((value) => value + 1) }}>Retry review</button></div>}
    <div className="posting-filters"><SearchField id="history-review-search" label="Search history" placeholder="Resident, MCR or original label" value={query} disabled={busy} onChange={(value) => { setQuery(value); setPage(0) }} /><label>Review status<select value={filter} disabled={busy} onChange={(event) => { setFilter(event.target.value); setPage(0) }}><option value="open">Needs review</option><option value="all">All entries</option><option value="reviewed">Label and year confirmed</option></select></label></div>
    <div aria-busy={busy} className={busy ? 'history-loading' : ''}>
      {busy && <p className="history-help" role="status">Checking history and saved decisions…</p>}
      {data && !error && (visible.length ? <div className="table-scroll"><table className="history-review-table"><caption className="sr-only">Historical posting labels, catalogue candidates and review decisions</caption><thead><tr><th scope="col">Resident / recorded year</th><th scope="col">Original posting / dates</th><th scope="col">Catalogue candidates</th><th scope="col">Review / reasons</th><th scope="col">Action</th></tr></thead><tbody>{visible.map((entry) => <Fragment key={entry.id}>
        <tr><th scope="row">{entry.name || 'Name missing'}<small>{entry.mcr || 'MCR missing'} · Recorded {entry.recorded_year || 'year missing'}</small></th>
          <td><span className="history-original">{entry.months[0].value}</span><small>{period(entry)} · {entry.months.length} {entry.months.length === 1 ? 'month' : 'months'}</small><details><summary>Workbook sources</summary>{entry.sources.map((source, index) => <small key={index}>{sourceLabel(source)}</small>)}</details></td>
          <td>{entry.review.target ? <><strong>{targetLabel(entry.review.target)}</strong><small>{entry.match.reasons.includes('remediation_credit_review') ? 'Recognized label' : entry.review.status === 'automatic_match' ? 'Automatic label match' : 'Confirmed label'}{entry.review.requirement_year ? ` · Requirement ${entry.review.requirement_year}` : ['automatic_match', 'credit_review_required'].includes(entry.review.status) ? ' - No requirement year assigned' : ' - Requirement year open'}</small>{entry.match.candidates.some((candidate) => candidate.key !== entry.review.target?.key) && <details><summary>Other catalogue alternatives</summary><ul className="history-candidates">{entry.match.candidates.filter((candidate) => candidate.key !== entry.review.target?.key).map((candidate, index) => <li key={index}>{targetLabel(candidate)}<small>{sourceLabel(candidate.source)}</small></li>)}</ul></details>}</> : entry.match.candidates.length ? <ul className="history-candidates">{entry.match.candidates.map((candidate, index) => <li key={index}>{targetLabel(candidate)}<small>{candidate.year_context === 'recorded_year' ? 'Within recorded R-year context' : candidate.year_context === 'earlier_remediation_year' ? 'Earlier year eligible for remediation matching' : candidate.year_context === 'earlier_fallback_year' ? 'Earlier-year fallback candidate' : candidate.year_context === 'different_year' ? 'Different from recorded R-year' : 'Year context unknown'}</small></li>)}</ul> : 'No exact catalogue match'}</td>
          <td><strong>{historyStatusLabel(entry.review.status)}</strong><ul className="history-reasons">{[...new Set([...(entry.review.target ? entry.match.reasons.filter((reason) => ['remediation_credit_review', 'earlier_year_fallback', 'recorded_year_unknown', 'catalogue_year_unknown', 'mixed_catalogue_years', 'requirement_year_review'].includes(reason)) : entry.match.reasons), ...entry.review.reasons])].map((reason) => <li key={reason}>{reasonLabel(reason)}</li>)}</ul></td>
          <td><button className="button button-secondary" type="button" aria-expanded={selected === entry.id} disabled={busy || storageBlocked} onClick={(event) => { reviewButton.current = event.currentTarget; setSelected(selected === entry.id ? null : entry.id) }}>Review<span className="sr-only"> {entry.name || entry.mcr}, {period(entry)}</span></button></td>
        </tr>{selected === entry.id && <tr><td colSpan={5}><fieldset disabled={busy}><DecisionEditor key={entry.id} entry={entry} catalogue={data.catalogue} store={store} onSave={save} onCancel={() => { setSelected(null); reviewButton.current?.focus() }} /></fieldset></td></tr>}
      </Fragment>)}</tbody></table></div> : <p className="empty-note">{data.entries.length ? filter === 'open' ? 'No historical entries match these filters. Choose All entries to see matched and confirmed labels.' : 'No historical entries match these filters.' : 'No posting entries were found in the annual tabs.'}</p>)}
    </div>
    {entries.length > 0 && <div className="history-pagination"><p>{entries.length} grouped entries · Page {currentPage + 1} of {pages}</p><div><button className="button button-secondary" type="button" disabled={busy || currentPage === 0} onClick={() => { setPage(currentPage - 1); setSelected(null) }}>Previous</button><button className="button button-secondary" type="button" disabled={busy || currentPage + 1 === pages} onClick={() => { setPage(currentPage + 1); setSelected(null) }}>Next</button></div></div>}
    <details className="history-saved"><summary>Saved decisions ({store.decisions.length}){unapplied ? ` · ${unapplied} unapplied or needing review` : ''}</summary>
      <p className="history-help">Missing periods remain saved for other imports. Changed context or catalogue entries require a new decision. Removing a shared mapping affects every matching label in its scope.</p>
      {data?.decisions.length ? <div className="table-scroll"><table><caption className="sr-only">Saved history review decisions</caption><thead><tr><th scope="col">Scope</th><th scope="col">Catalogue target</th><th scope="col">Status</th><th scope="col">Action</th></tr></thead><tbody>{data.decisions.map((state, index) => <tr key={`${state.key}-${index}`}><td>{state.decision.kind === 'alias' ? <><strong>Shared label mapping</strong><p>{state.decision.context.label}</p><small>Recorded {state.decision.context.recorded_year || 'year blank'} · {state.decision.context.category}</small></> : <><strong>Resident {state.decision.context.mcr}</strong><p>{period(state.decision.context)}</p><small>Recorded {state.decision.context.recorded_year || 'year blank'} · Requirement {state.decision.requirement_year || 'unconfirmed'}</small></>}</td><td>{state.target ? targetLabel(state.target) : 'Target missing from this catalogue'}</td><td>{state.status === 'applied' ? 'Applied' : state.status === 'not_present' ? 'Not present in this import' : 'Needs review'}{state.reasons.map((reason) => <small key={reason}>{reasonLabel(reason)}</small>)}</td><td><button className="button button-secondary" type="button" disabled={busy || storageBlocked} onClick={() => persist({ version: 1, decisions: store.decisions.filter((decision) => decisionKey(decision) !== state.key) })}>Remove decision</button></td></tr>)}</tbody></table></div> : <p className="history-help">No decisions saved yet. Review an entry above to begin.</p>}
    </details>
  </div>
}
