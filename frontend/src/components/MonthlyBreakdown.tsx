import { useEffect, useMemo, useRef, useState } from 'react'
import { scrollToPosition } from '../lib/scroll'
import type { Workbook } from '../lib/workbook'
import { monthLabel } from '../lib/workbook'
import type { DraftSchedule } from '../lib/draft-schedule'
import type { HistoryEntry } from '../lib/history-review'
import { monthlyBreakdown } from '../lib/monthly-breakdown'

export default function MonthlyBreakdown({ workbook, draft, entries }: { workbook: Workbook; draft: DraftSchedule | null; entries: HistoryEntry[] }) {
  const [year, setYear] = useState('R1')
  const [collapsed, setCollapsed] = useState<string[]>([])
  const openingGroup = useRef<HTMLTableSectionElement | null>(null)
  useEffect(() => {
    const target = openingGroup.current
    openingGroup.current = null
    if (!target) return
    const rect = target.getBoundingClientRect()
    if (rect.top >= 16 && rect.bottom <= window.innerHeight - 16) return
    const offset = rect.height > window.innerHeight - 32 ? 16 : (window.innerHeight - rect.height) / 2
    return scrollToPosition(window.scrollY + rect.top - offset)
  }, [collapsed, year])
  const years = ['R1', 'R2', 'R3', 'R4', 'R5']
  const selectedYear = years.includes(year) ? year : 'R1'
  const groups = useMemo(() => monthlyBreakdown(workbook, draft, entries, selectedYear), [workbook, draft, entries, selectedYear])
  return <section className="workspace-panel monthly-breakdown" aria-labelledby="breakdown-heading">
    <div className="breakdown-toolbar"><div><h2 id="breakdown-heading">Monthly breakdown</h2><p className="muted">Jul {workbook.target_year} - Jun {workbook.target_year + 1}</p></div>
      <select aria-label="Residency year" value={selectedYear} onChange={(event) => setYear(event.target.value)}>{years.map((value) => <option key={value}>{value}</option>)}</select>
    </div>
    {groups.length ? <div className="table-scroll"><table>
      <caption className="sr-only">Monthly resident counts across the full cohort, independent of resident search. Filtered by {selectedYear || 'requirement years'}.</caption>
      <thead><tr><th scope="col">Posting / Institution</th>{workbook.months.map(({ month }) => <th key={month} scope="col">{monthLabel(month)}</th>)}</tr></thead>
      {groups.map((group) => <tbody key={group.key}>
        <tr className="breakdown-group"><th scope="row">{group.institutions.length ? <button type="button" aria-expanded={!collapsed.includes(group.key)} onClick={(event) => {
          openingGroup.current = collapsed.includes(group.key) ? event.currentTarget.closest('tbody') : null
          setCollapsed((previous) => previous.includes(group.key) ? previous.filter((key) => key !== group.key) : [...previous, group.key])
        }}>
          <svg viewBox="0 0 16 16" aria-hidden="true" className={collapsed.includes(group.key) ? 'collapsed' : ''}><path d="m4 6 4 4 4-4" /></svg>{group.label}</button> : group.label}</th>
          {workbook.months.map(({ month }) => <td key={month}>{group.counts[month] || 0}</td>)}</tr>
        {!collapsed.includes(group.key) && group.institutions.map((site) => <tr className="breakdown-institution" key={site.label}><th scope="row">{site.label}</th>{workbook.months.map(({ month }) => {
          const description = site.capacity === null ? undefined : `All R-years: ${site.allCounts[month] || 0} residents. Catalogue maximum: ${site.capacity}.`
          return <td key={month}>{description ? <span tabIndex={0} title={description} aria-label={`${site.counts[month] || 0} residents in selected years. ${description}`}>{site.counts[month] || 0}</span> : site.counts[month] || 0}</td>
        })}</tr>)}
      </tbody>)}
    </table></div> : <p className="empty-note">No monthly assignments for this selection.</p>}
  </section>
}
