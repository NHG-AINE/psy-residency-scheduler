import { useId, useRef } from 'react'
import { draftBlockerLabel, groupedCapacityRows, groupedDraftWarnings } from '../lib/draft-schedule'
import type { DraftSchedule } from '../lib/draft-schedule'
import { monthLabel, sameSource, sourceLabel } from '../lib/workbook'
import type { Source, Workbook } from '../lib/workbook'

function ResidentWarnings({ people, title, canFind, onFind, initiallyOpen }: {
  people: NonNullable<DraftSchedule['skipped_residents']>; title: string; canFind: (source: Source) => boolean; onFind: (source: Source) => void; initiallyOpen: boolean
}) {
  return <details open={initiallyOpen}>
    <summary>{title} <span className="muted">{people.length} {people.length === 1 ? 'resident' : 'residents'}</span></summary>
    <div className="draft-review-items">{people.map((person, index) => <div key={index}>
        <strong>{person.name || person.mcr || sourceLabel(person.source)}</strong>
        {person.name && person.mcr && <p className="draft-warning-source">{person.mcr}</p>}
        <ul>{groupedDraftWarnings(person.reasons).map((warning, warningIndex) => <li key={warningIndex}>
          <span>{warning.reason}{warning.dates && ` · ${warning.dates}`}</span>
          {warning.sources.length > 0 && <p className="draft-warning-source">Source: {warning.sources.join('; ')}</p>}
        </li>)}</ul>
        {canFind(person.source) && <button type="button" className="draft-find" onClick={() => onFind(person.source)}>Find in timetable</button>}
      </div>)}</div>
  </details>
}

export default function DraftReview({ draft, workbook, yearLabel, onFind }: {
  draft: DraftSchedule; workbook: Workbook; yearLabel: string; onFind: (source: Source) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const close = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const skipped = draft.skipped_residents ?? []
  const historical = draft.historical_cluster_warnings ?? []
  const overflows = groupedCapacityRows(draft.capacity_overflows ?? [])
  const coverage = new Map<string, { code: string; source: Source; labels: Set<string> }>()
  for (const note of draft.capacity_coverage_notes ?? []) {
    const { source, code } = note
    const key = JSON.stringify([source.kind ? source.slot_id : [source.sheet, source.row], code])
    const group = coverage.get(key) ?? { code, source, labels: new Set<string>() }
    group.labels.add(sourceLabel(source))
    coverage.set(key, group)
  }
  const groups = [skipped.length, historical.length, overflows.length, coverage.size].filter(Boolean).length

  const canFind = (source: Source) => workbook.residents.some((resident) => sameSource(resident.source, source))
  function find(source: Source) {
    dialog.current?.close()
    onFind(source)
  }

  return <>
    <button type="button" className={`button button-secondary${groups ? ' draft-review-trigger' : ''}`} aria-haspopup="dialog" onClick={() => {
      dialog.current?.showModal()
      close.current?.focus()
    }}>Review draft <span className="draft-review-count" aria-label={`${groups} warning ${groups === 1 ? 'group' : 'groups'}`}>{groups}</span></button>
    <dialog ref={dialog} className="draft-review-panel" aria-labelledby={titleId}>
      <header>
        <div><h3 id={titleId}>Draft review</h3><p className="muted">{yearLabel}</p></div>
        <button ref={close} type="button" className="request-close" aria-label="Close draft review" onClick={() => dialog.current?.close()}>
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 4 8 8m0-8-8 8" /></svg>
        </button>
      </header>
      {!groups && <p className="muted">No draft warnings.</p>}
      {skipped.length > 0 && <ResidentWarnings people={skipped} title="Residents left unchanged" canFind={canFind} onFind={find} initiallyOpen />}
      {historical.length > 0 && <ResidentWarnings people={historical} title="Historical cluster warnings" canFind={canFind} onFind={find} initiallyOpen={!skipped.length} />}
      {overflows.length > 0 && <details>
        <summary>Postings over capacity <span className="muted">{overflows.length} {overflows.length === 1 ? 'posting' : 'postings'}</span></summary>
        <div className="draft-review-items">{overflows.map((group) => <div key={group.key}>
          <strong>{group.label}</strong>
          <p className="draft-warning-source">Source: {sourceLabel(group.source)}</p>
          <ul>{group.periods.map((period) => <li key={period.start}>
            {monthLabel(period.start)}{period.end !== period.start && ` – ${monthLabel(period.end)}`} · {period.assigned} assigned / {period.max} max · {period.assigned - period.max} over
          </li>)}</ul>
        </div>)}</div>
      </details>}
      {coverage.size > 0 && <details>
        <summary>Capacity counts need review <span className="muted">{coverage.size} {coverage.size === 1 ? 'record' : 'records'} excluded</span></summary>
        <div className="draft-review-items">{[...coverage].map(([key, note]) => {
          const resident = workbook.residents.find((person) => sameSource(person.source, note.source))
          return <div key={key}>
            <strong>{resident?.name || resident?.mcr || 'Unnamed resident'}</strong>
            <p>{draftBlockerLabel({ code: note.code }, workbook)}</p>
            <p className="draft-warning-source">Source: {[...note.labels].join('; ')}</p>
            {resident && <button type="button" className="draft-find" onClick={() => find(note.source)}>Find in timetable</button>}
          </div>
        })}</div>
      </details>}
    </dialog>
  </>
}
