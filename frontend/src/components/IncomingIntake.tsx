import { useRef, useState } from 'react'
import type { Workbook } from '../lib/workbook'
import { sameSource } from '../lib/workbook'
import { emptyIntakeStore, makeIntakeLink, mergeIntakeStores, parseIntakeStore } from '../lib/intake-links'
import type { IntakeLinkStore } from '../lib/intake-links'

export default function IncomingIntake({ workbook, store, storageError, busy, onSave, onIssues }: {
  workbook: Workbook; store: IntakeLinkStore; storageError: string; busy: boolean
  onSave: (store: IntakeLinkStore, discardUnreadable?: boolean) => Promise<void>; onIssues: () => void
}) {
  const [mcr, setMcr] = useState(''), [slotId, setSlotId] = useState('')
  const [error, setError] = useState(''), [message, setMessage] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const year = workbook.target_year
  const cohort = workbook.residents.filter((row) => row.residency_year?.trim().toUpperCase() === 'R1' && row.intake?.trim() === String(year))
  const blocked = (row: typeof cohort[number]) => workbook.issues?.some((issue) => ['missing_mcr', 'missing_name', 'duplicate_mcr', 'conflicting_identity', 'duplicate_intake_placeholder'].includes(issue.code) && issue.records?.some((record) => sameSource(record.source, row.source)))
  const people = cohort.filter((row) => row.mcr?.trim() && row.name?.trim() && !row.slot_id && !blocked(row)
    && !store.links.some((link) => link.year === year && link.mcr.trim().toLowerCase() === row.mcr?.trim().toLowerCase()))
  const slots = cohort.filter((row) => row.is_intake_placeholder && row.slot_id && !blocked(row)
    && !store.links.some((link) => link.slot_id === row.slot_id))
  const person = people.find((row) => row.mcr === mcr), slot = slots.find((row) => row.slot_id === slotId)
  const disabled = busy || !!storageError
  async function save(next: IntakeLinkStore, discardUnreadable = false) {
    setError(''); setMessage('')
    try { await onSave(next, discardUnreadable); setMessage('Intake links saved in this browser.'); return true }
    catch (problem) { setError(problem instanceof Error ? problem.message : 'Intake links could not be saved. Retry.'); return false }
  }
  function exportLinks() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(store, null, 2)], { type: 'application/json' }))
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'incoming-intake-links.json'; anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  async function importLinks(file: File) {
    setError(''); setMessage('')
    try {
      if (file.size > 10 * 1024 * 1024) throw new Error('Choose an intake-link JSON file of 10 MB or smaller.')
      await save(mergeIntakeStores(store, parseIntakeStore(await file.text())))
    } catch (problem) { setError(problem instanceof Error ? problem.message : 'Intake links could not be imported.') }
  }
  const warnings = workbook.issues?.filter((issue) => ['unclear_intake', 'excess_intake', 'duplicate_intake_placeholder', 'intake_fill_blocked'].includes(issue.code)) || []
  return <details className="incoming-intake">
    <summary>Incoming R1 - {year}: {cohort.filter((row) => !row.is_intake_placeholder).length} named, {cohort.filter((row) => row.is_intake_placeholder).length} placeholders</summary>
    <div className="incoming-intake-content">
      <p>Link a named incoming resident to their placeholder. Compatible postings are retained; vacancies are filled to 24.</p>
      <p className="muted">Saved in this browser; export a backup for another browser. Changed identities or conflicting postings need review.</p>
      {warnings.length > 0 && <div className="history-warning"><p>{warnings.length} incoming intake issues need review. An excess count can be resolved by confirming a resident-to-slot link.</p><button className="button button-secondary" type="button" onClick={onIssues} disabled={busy}>Review Issues</button></div>}
      {storageError && <div role="alert" className="history-warning"><p>Saved intake links could not be read. {storageError}</p><p>Keep the saved data and repair it, or explicitly discard it to start again. The workbook remains available.</p><button type="button" className="button button-secondary" disabled={busy} onClick={() => void save(emptyIntakeStore(), true)}>Discard unreadable intake links and start new</button></div>}
      <form className="intake-link-form" onSubmit={async (event) => { event.preventDefault(); if (person && slot && await save({ version: 1, links: [...store.links, makeIntakeLink(year, person, slot)] })) { setMcr(''); setSlotId('') } }}>
        <label>Named incoming resident<select value={mcr} disabled={disabled} onChange={(event) => setMcr(event.target.value)}><option value="">Choose a resident</option>{people.map((row) => <option key={row.mcr} value={row.mcr!}>{row.name} - {row.mcr}</option>)}</select></label>
        <label>Intake slot<select value={slotId} disabled={disabled} onChange={(event) => setSlotId(event.target.value)}><option value="">Choose a placeholder</option>{slots.map((row) => <option key={row.slot_id} value={row.slot_id}>{row.name} - {row.slot_id}</option>)}</select></label>
        <button className="button" disabled={disabled || !person || !slot} type="submit">Confirm link</button>
      </form>
      {!people.length && <p className="muted">No unlinked incoming residents with a safe MCR identity are available.</p>}
      <div className="history-actions"><button className="button button-secondary" type="button" onClick={exportLinks} disabled={busy || !!storageError || !store.links.length}>Export intake links</button><button className="button button-secondary" type="button" onClick={() => input.current?.click()} disabled={disabled}>Import intake links</button><input ref={input} type="file" hidden accept=".json,application/json" aria-label="Intake link JSON file" disabled={disabled} onChange={(event) => { const file = event.target.files?.[0]; if (file) void importLinks(file); event.target.value = '' }} /></div>
      {!!store.links.length && <div className="table-scroll"><table><caption>Saved intake links</caption><thead><tr><th>Resident</th><th>Intake slot</th><th>Status</th><th>Action</th></tr></thead><tbody>{store.links.map((link) => {
        const state = workbook.intake_links?.find((item) => item.slot_id === link.slot_id)
        return <tr key={link.slot_id}><td>{link.name}<small>{link.mcr}</small></td><td>{link.slot_id}</td><td>{state?.status === 'applied' ? 'Applied' : state?.status === 'other_year' ? 'Other planning year' : 'Needs review'}<small>{state?.message || 'Re-import the workbook to review this link.'}</small></td><td><button type="button" className="button button-secondary" aria-label={`Remove link for ${link.name}`} disabled={disabled} onClick={() => void save({ version: 1, links: store.links.filter((item) => item.slot_id !== link.slot_id) })}>Remove link</button></td></tr>
      })}</tbody></table></div>}
      <p role="status">{busy ? 'Saving intake links...' : message}</p>{error && <p className="error-message" role="alert">{error}</p>}
    </div>
  </details>
}
