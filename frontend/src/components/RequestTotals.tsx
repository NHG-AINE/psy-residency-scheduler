import { requestTotals } from '../lib/draft-schedule'
import type { DraftSchedule, RequestStatus } from '../lib/draft-schedule'

export default function RequestTotals({ draft, selected, onChange }: {
  draft: DraftSchedule; selected: RequestStatus | null; onChange: (status: RequestStatus | null) => void
}) {
  const counts = requestTotals(draft)
  if (!Object.values(counts).some(Boolean)) return null
  return <div className="request-totals" role="group" aria-label="Filter timetable by request outcome">
    <div className="request-total-buttons">
      <button type="button" aria-pressed={selected === null} onClick={() => onChange(null)}>All</button>
      {(['met', 'not_met', 'pending'] as const).map((status) => (status !== 'pending' || counts.pending > 0) &&
        <button type="button" key={status} className={status} aria-pressed={selected === status}
          title={`${counts[status]} requests ${status === 'not_met' ? 'not met' : status} across the whole draft. Click to ${selected === status ? 'show all residents' : 'filter residents'}.`}
          onClick={() => onChange(selected === status ? null : status)}>
          <svg viewBox="0 0 16 16" aria-hidden="true">
            {status === 'met' ? <path d="m3 8 3 3 7-7" /> : status === 'not_met'
              ? <><path d="M8 2 15 14H1Z" /><path d="M8 6v4m0 2v.5" /></>
              : <><circle cx="8" cy="8" r="6" /><path d="M8 4v4l2 1" /></>}
          </svg>
          <span>{counts[status]} {status === 'not_met' ? 'not met' : status}</span>
        </button>)}
    </div>
  </div>
}
