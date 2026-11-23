import { requestTotals } from '../lib/draft-schedule'
import type { DraftSchedule, RequestStatus } from '../lib/draft-schedule'

export default function RequestOutcomeFilter({ draft, selected, onChange, disabled }: {
  draft: DraftSchedule | null; selected: RequestStatus | null; onChange: (status: RequestStatus | null) => void; disabled: boolean
}) {
  const { met, not_met, pending } = requestTotals(draft)
  const total = met + not_met + pending
  if (!total) return null
  return <label className="request-outcome-filter">Request outcome
    <select value={selected ?? ''} disabled={disabled} onChange={(event) => onChange((event.target.value || null) as RequestStatus | null)}>
      <option value="">All request outcomes ({total})</option>
      <option value="met">Met ({met})</option>
      <option value="not_met">Not met ({not_met})</option>
      {pending > 0 && <option value="pending">Pending ({pending})</option>}
    </select>
  </label>
}
