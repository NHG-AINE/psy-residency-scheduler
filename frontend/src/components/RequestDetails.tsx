import type { ReactNode } from 'react'
import type { RequestOutcome } from '../lib/draft-schedule'
import { monthLabel } from '../lib/workbook'
import DetailsPopover from './DetailsPopover'

export default function RequestDetails({ name, rows, hint, className, children }: {
  name: string; rows: RequestOutcome[]; hint: string; className: string; children: ReactNode
}) {
  return <DetailsPopover name={name} hint={hint} className={className} details={rows.map((row, index) => <article key={index}>
        <p className={`request-status ${row.status}`}>{row.status === 'met' ? 'Request met' : row.status === 'not_met' ? 'Request not met' : 'Pending clarification'}</p>
        <dl><dt>Requested</dt><dd>{row.request.posting_request}<small>{row.request.period || 'Any time in planning year'}</small></dd>
          {!!row.assigned?.length && <><dt>Assigned</dt><dd>{row.assigned.map((item, i) => <div key={i}>{item.label}<small>{item.months.map(monthLabel).join(', ')}</small></div>)}</dd></>}
          {row.reason && <><dt>{row.status === 'not_met' ? "Why this wasn't met" : 'Clarification needed'}</dt><dd>{row.reason}</dd></>}
        </dl>
      </article>)}>{children}</DetailsPopover>
}
