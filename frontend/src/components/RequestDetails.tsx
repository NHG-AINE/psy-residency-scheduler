import type { ReactNode } from 'react'
import { groupedCapacityRows, monthRanges } from '../lib/draft-schedule'
import type { RequestOutcome } from '../lib/draft-schedule'
import DetailsPopover from './DetailsPopover'

const requestMonths = new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })
const monthNames = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']

function formatRequestRange(start: string, end: string) {
  return requestMonths.formatRange(new Date(start), new Date(end)).replace(/\s*–\s*/g, '–')
}

function monthNumber(name: string) {
  const lower = name.toLowerCase().replace(/^sept$/, 'sep')
  return monthNames.findIndex((full) => lower === full || lower === full.slice(0, 3)) + 1
}

function requestedWindow(period: string) {
  const match = /^([a-z]+)(?:\s+(\d{4}))?(?:\s*[-–]\s*([a-z]+)\s+(\d{4}))?$/i.exec(period)
  if (!match) return null
  const [, first, firstYear, last = first, lastYear = firstYear] = match
  const startYear = firstYear ?? lastYear
  const startMonth = monthNumber(first)
  const endMonth = monthNumber(last)
  if (!Number(startYear) || !Number(lastYear) || !startMonth || !endMonth) return null
  const months = (Number(lastYear) - Number(startYear)) * 12 + endMonth - startMonth + 1
  if (months < 1) return null
  const start = `${startYear}-${String(startMonth).padStart(2, '0')}`
  const end = `${lastYear}-${String(endMonth).padStart(2, '0')}`
  return { label: formatRequestRange(start, end), months }
}

function requestedTiming(row: RequestOutcome) {
  const period = String(row.request.period ?? '')
  const window = row.reason === 'Period is unclear or outside the planning year' ? null : requestedWindow(period.trim())
  const label = window?.label ?? (period.trim() ? period : 'Any time in planning year')
  const durations = row.requested_durations?.length ? row.requested_durations : row.requested_months ? [row.requested_months] : []
  if (!durations.length || (durations.length === 1 && durations[0] === window?.months)) return label
  return `${label} · ${durations.join(' or ')} ${durations.length === 1 && durations[0] === 1 ? 'month' : 'months'}`
}

export default function RequestDetails({ name, rows, hint, className, children }: {
  name: string; rows: RequestOutcome[]; hint: string; className: string; children: ReactNode
}) {
  return <DetailsPopover name={name} hint={hint} className={className}
    details={rows.map((row, index) => <RequestOutcomeDetails key={index} row={row} />)}>{children}</DetailsPopover>
}

export function RequestOutcomeDetails({ row }: { row: RequestOutcome }) {
  const capacity = groupedCapacityRows(row.capacity ?? [])
  const periods = capacity.map(({ key, label, periods }) => <div className="request-capacity-posting" key={key}>
    <p>{label}</p>
    <ul className="request-capacity-periods">
      {periods.map(({ start, end, assigned, max }) => <li key={start}>
        <span>{formatRequestRange(start, end)}</span>
        <span className={assigned >= max ? 'at-max' : undefined}>{assigned} assigned / {max} max</span>
      </li>)}
    </ul>
  </div>)
  return <article>
        <p className={`request-status ${row.status}`}>{row.status === 'met' ? 'Request met' : row.status === 'not_met' ? 'Request not met' : 'Pending clarification'}</p>
        <dl><dt>{row.alternatives ? 'Requested alternatives' : 'Requested'}</dt><dd>{(row.alternatives || [row]).map((option, i) => <div key={i}>
          {i > 0 && <small>OR</small>}
          {option.request.posting_request}
          <small>{requestedTiming(option)}</small>
          {row.alternatives && option.status === 'met' && <small className="request-status met">Selected</small>}
          {row.alternatives && row.status === 'not_met' && option.reason !== row.reason && <small>{option.reason}</small>}
        </div>)}</dd>
          {!!row.assigned?.length && <><dt>Assigned</dt><dd>{row.assigned.map((item, i) => <div key={i}>{item.label}<small>{monthRanges(item.months, formatRequestRange)}</small></div>)}</dd></>}
          {row.reason && <><dt>{row.status === 'not_met' ? "Why this wasn't met" : 'Clarification needed'}</dt><dd>{row.reason}</dd></>}
        </dl>
        {row.status === 'not_met' && !!capacity.length && <details className="request-capacity">
          <summary>Capacity in this draft</summary>{periods}
        </details>}
      </article>
}
