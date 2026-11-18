import { groupedDraftWarnings } from '../lib/draft-schedule'
import type { DraftSchedule } from '../lib/draft-schedule'
import { sourceLabel } from '../lib/workbook'

export default function DraftResidentWarnings({ draft }: { draft: DraftSchedule }) {
  const skipped = draft.skipped_residents ?? []
  const historical = draft.historical_cluster_warnings ?? []
  return <>
    {skipped.length > 0 && <ResidentWarnings people={skipped}
      summary={`${skipped.length} ${skipped.length === 1 ? 'resident left' : 'residents left'} unchanged - review input issues`} />}
    {historical.length > 0 && <ResidentWarnings people={historical}
      summary={`${historical.length} ${historical.length === 1 ? 'resident has' : 'residents have'} historical cluster warnings`} />}
  </>
}

function ResidentWarnings({ people, summary }: {
  people: NonNullable<DraftSchedule['skipped_residents']>; summary: string
}) {
  return <details>
    <summary>{summary}</summary>
    <div className="draft-resident-warnings">{people.map((person, index) => <div key={index}>
      <strong>{person.name || person.mcr || sourceLabel(person.source)}</strong>
      <ul>{groupedDraftWarnings(person.reasons).map((warning, warningIndex) => <li key={warningIndex}>
        <span>{warning.reason}{warning.dates && ` \u00b7 ${warning.dates}`}</span>
        {warning.sources.length > 0 && <p className="draft-warning-source">Source: {warning.sources.join('; ')}</p>}
      </li>)}</ul>
    </div>)}</div>
  </details>
}
