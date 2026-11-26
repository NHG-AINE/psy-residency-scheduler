import { useEffect, useMemo, useRef, useState } from 'react'
import { scrollToPosition } from '../lib/scroll'
import type { Workbook } from '../lib/workbook'
import { monthLabel } from '../lib/workbook'
import type { DraftSchedule } from '../lib/draft-schedule'
import type { HistoryEntry, RecordedCompletion } from '../lib/history-review'
import CapacityDetails from './CapacityDetails'
import { monthlyBreakdown } from '../lib/monthly-breakdown'

export default function MonthlyBreakdown({ workbook, draft, entries, completions }: {
  workbook: Workbook; draft: DraftSchedule | null; entries: HistoryEntry[]; completions?: RecordedCompletion[]
}) {
  const [year, setYear] = useState('R1')
  const [capacityFocus, setCapacityFocus] = useState<{ group: string; site: string; month: string; request: number } | null>(null)
  const [expanded, setExpanded] = useState<string[]>([])
  const openingGroup = useRef<HTMLTableSectionElement | null>(null)
  useEffect(() => {
    const target = openingGroup.current
    openingGroup.current = null
    if (!target) return
    const rect = target.getBoundingClientRect()
    if (rect.top >= 16 && rect.bottom <= window.innerHeight - 16) return
    const offset = rect.height > window.innerHeight - 32 ? 16 : (window.innerHeight - rect.height) / 2
    return scrollToPosition(window.scrollY + rect.top - offset)
  }, [expanded, year])
  const years = ['R1', 'R2', 'R3', 'R4', 'R5']
  const selectedYear = years.includes(year) ? year : 'R1'
  const groups = useMemo(() => monthlyBreakdown(workbook, draft, entries, selectedYear, completions), [workbook, draft, entries, selectedYear, completions])
  return <section className="workspace-panel monthly-breakdown" aria-labelledby="breakdown-heading">
    <div className="breakdown-toolbar"><div><h2 id="breakdown-heading">Monthly breakdown</h2><p className="muted">Jul {workbook.target_year} - Jun {workbook.target_year + 1} &middot; Postings count by requirement year. LOA, unallocated months, unresolved postings and older draft assignments without a requirement year count by resident cohort.</p></div>
      <label>Programme year<select value={selectedYear} onChange={(event) => { setCapacityFocus(null); setYear(event.target.value) }}>{years.map((value) => <option key={value}>{value}</option>)}</select></label>
    </div>
    {groups.length ? <div className="table-scroll"><table>
      <caption className="sr-only">Monthly counts for programme year {selectedYear} across all residents, independent of resident search. LOA, unallocated months, unresolved postings and older draft assignments without a requirement year are grouped by resident cohort.</caption>
      <thead><tr><th scope="col">Posting / Institution</th>{workbook.months.map(({ month }) => <th key={month} scope="col">{monthLabel(month)}</th>)}</tr></thead>
      {groups.map((group) => <tbody key={group.key}>
        <tr className="breakdown-group"><th scope="row">{group.institutions.length ? <button type="button" aria-expanded={expanded.includes(group.key)} onClick={(event) => {
          setCapacityFocus(null)
          openingGroup.current = !expanded.includes(group.key) ? event.currentTarget.closest('tbody') : null
          setExpanded((previous) => previous.includes(group.key) ? previous.filter((key) => key !== group.key) : [...previous, group.key])
        }}>
          <svg viewBox="0 0 16 16" aria-hidden="true" className={!expanded.includes(group.key) ? 'collapsed' : ''}><path d="m4 6 4 4 4-4" /></svg>{group.label}</button> : group.label}</th>
          {workbook.months.map(({ month }) => {
            const rows = group.institutions.flatMap((site) => site.overflows.filter((row) => row.month === month))
            return <td key={month} className={rows.length ? 'capacity-overflow-cell' : undefined}>{rows.length ? <button type="button" className="capacity-warning" title="Expand to review the institution over max" aria-label={`${group.label}, ${monthLabel(month)}: expand to review the institution over max`} onClick={() => {
              const site = group.institutions.find((item) => item.overflows.some((row) => row.month === month))!
              openingGroup.current = null
              setExpanded((previous) => previous.includes(group.key) ? previous : [...previous, group.key])
              setCapacityFocus((previous) => ({ group: group.key, site: site.label, month, request: (previous?.request || 0) + 1 }))
            }}>{group.counts[month] || 0}</button> : group.counts[month] || 0}</td>
          })}</tr>
        {expanded.includes(group.key) && group.institutions.map((site) => <tr className="breakdown-institution" key={site.label}><th scope="row">{site.label}</th>{workbook.months.map(({ month }) => {
          const rows = site.overflows.filter((row) => row.month === month)
          return <td key={month} className={rows.length ? 'capacity-overflow-cell' : undefined}>{rows.length ? <CapacityDetails rows={rows} openRequest={capacityFocus?.group === group.key && capacityFocus.site === site.label && capacityFocus.month === month ? capacityFocus.request : 0}>{site.counts[month] || 0}</CapacityDetails> : site.counts[month] || 0}</td>
        })}</tr>)}
      </tbody>)}
    </table></div> : <p className="empty-note">No monthly assignments for this selection.</p>}
  </section>
}
