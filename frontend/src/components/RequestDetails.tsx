import type { ReactNode } from 'react'
import { groupedCapacityRows, monthRanges } from '../lib/draft-schedule'
import type { RequestOutcome } from '../lib/draft-schedule'
import DetailsPopover from './DetailsPopover'

const capacityMonths = new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })

export default function RequestDetails({ name, rows, hint, className, children }: {
  name: string; rows: RequestOutcome[]; hint: string; className: string; children: ReactNode
}) {
  return <DetailsPopover name={name} hint={hint} className={className} details={rows.map((row, index) => <article key={index}>
        <p className={`request-status ${row.status}`}>{row.status === 'met' ? 'Request met' : row.status === 'not_met' ? 'Request not met' : 'Pending clarification'}</p>
        <dl><dt>Requested</dt><dd>{row.request.posting_request}<small>{row.request.period || 'Any time in planning year'}{row.requested_months ? <> &middot; {row.requested_durations?.join(' or ') || row.requested_months} {row.requested_months === 1 ? 'month' : 'months'}</> : null}</small></dd>
          {!!row.assigned?.length && <><dt>Assigned</dt><dd>{row.assigned.map((item, i) => <div key={i}>{item.label}<small>{monthRanges(item.months)}</small></div>)}</dd></>}
          {row.reason && <><dt>{row.status === 'not_met' ? "Why this wasn't met" : 'Clarification needed'}</dt><dd>{row.reason}</dd></>}
        </dl>
        {row.status === 'not_met' && !!row.capacity?.length && <details className="request-capacity">
          <summary>Capacity in this draft</summary>
          {groupedCapacityRows(row.capacity).map(({ key, label, periods }) => <div className="request-capacity-posting" key={key}>
            <p>{label}</p>
            <ul className="request-capacity-periods">
              {periods.map(({ start, end, assigned, max }) => <li key={start}>
                <span>{capacityMonths.formatRange(new Date(start), new Date(end)).replaceAll('\u2009', '')}</span>
                <span className={assigned >= max ? 'at-max' : undefined}>{assigned} assigned / {max} max</span>
              </li>)}
            </ul>
          </div>)}
        </details>}
      </article>)}>{children}</DetailsPopover>
}
