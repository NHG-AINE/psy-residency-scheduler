import type { Workbook } from './workbook.ts'
import { sameSource } from './workbook.ts'
import { resolvedCatalogueTarget } from './history-review.ts'
import type { DraftSchedule } from './draft-schedule.ts'
import type { HistoryEntry } from './history-review.ts'
import { draftPostings } from './draft-schedule.ts'
import { postingCategory, postingDisplay, postingHistoryEntry } from './posting-blocks.ts'

type Counts = Record<string, number>
export type BreakdownGroup = { key: string; label: string; counts: Counts; institutions: {
  label: string; counts: Counts; allCounts: Counts; capacity: number | null
}[] }

export function monthlyBreakdown(workbook: Workbook, draft: DraftSchedule | null, entries: HistoryEntry[], year = '') {
  const groupElectives = year === 'R2' || year === 'R5'
  const groups = new Map<string, BreakdownGroup>()
  const capacities = new Map<string, Set<string | null>>()
  const groupFor = (label: string, category: string) => {
    const key = JSON.stringify([category, label.toLowerCase()])
    if (!groups.has(key)) groups.set(key, { key, label: category === 'elective' ? (groupElectives ? 'Electives' : `${label} (Elective)`) : label, counts: {}, institutions: [] })
    return groups.get(key)!
  }
  const siteFor = (label: string, category: string) => {
    // Catalogue labels use the same institution-prefix convention as the scheduler.
    const [institution, ...words] = label.trim().split(/\s+/)
    const groupedElective = groupElectives && category === 'elective'
    const group = groupFor(groupedElective ? 'Electives' : words.join(' ') || label, category)
    const rowLabel = groupedElective ? label : institution
    let site = group.institutions.find((item) => item.label === rowLabel)
    if (!site) {
      site = { label: rowLabel, counts: {}, allCounts: {}, capacity: null }
      group.institutions.push(site)
    }
    return { group, site }
  }
  for (const row of workbook.postings.core) {
    if (!row.posting) continue
    const values = capacities.get(row.posting) || new Set<string | null>()
    values.add(row.max)
    capacities.set(row.posting, values)
    siteFor(row.posting, 'core')
  }
  for (const row of workbook.postings.electives || []) {
    if (!groupElectives || row.residency_year === year) siteFor(`${row.institution} ${row.elective}`, 'elective')
  }
  const increment = (counts: Counts, month: string) => { counts[month] = (counts[month] || 0) + 1 }
  const months = new Set(workbook.months.map((month) => month.month))
  for (const resident of workbook.residents) {
    const planned = draft?.residents.find((person) => sameSource(person.source, resident.source))
    for (const posting of draftPostings(resident, draft)) {
      if (!months.has(posting.month)) continue
      const display = postingDisplay([posting], 'catalogue', entries)
      const category = postingCategory(display, posting.status)
      const entry = posting.draft ? undefined : postingHistoryEntry(posting, entries)
      const target = entry ? resolvedCatalogueTarget(entry.review) : null
      const requirementYear = posting.draft
        ? planned?.months.find((month) => month.month === posting.month)?.target?.residency_year
        : target ? entry?.review.requirement_year || target.residency_year : null
      // Non-posting months have no requirement year; only use an unambiguous recorded year.
      const recorded = resident.residency_year?.trim().toUpperCase()
      const applicableYear = requirementYear || (category !== 'core' && category !== 'elective' && /^R[1-5]$/.test(recorded || '') ? recorded : null)
      const included = !year || applicableYear === year
      if (category === 'core' || category === 'elective') {
        const { group, site } = siteFor(display.label, category)
        increment(site.allCounts, posting.month)
        if (included) { increment(group.counts, posting.month); increment(site.counts, posting.month) }
        const limits = capacities.get(display.label)
        const value = limits?.size === 1 ? [...limits][0] : null
        if (category === 'core' && value != null && /^\d+$/.test(value.trim())) site.capacity = Number(value)
      } else if (included) {
        const label = category === 'loa' ? 'LOA' : category === 'unallocated' ? 'Unallocated' : 'Unresolved'
        increment(groupFor(label, category).counts, posting.month)
      }
    }
  }
  const r1Order = ['General Medicine', 'Neurology', 'Medicine & Neurology', 'Inpatient Psychiatry']
  const rank = (group: BreakdownGroup) => year === 'R1' && r1Order.includes(group.label) ? r1Order.indexOf(group.label) : r1Order.length
  return [...groups.values()].filter((group) => Object.keys(group.counts).length)
    .sort((a, b) => rank(a) - rank(b) || Number(!a.institutions.length) - Number(!b.institutions.length) || a.label.localeCompare(b.label))
    .map((group) => ({ ...group, institutions: group.institutions.sort((a, b) => a.label.localeCompare(b.label)) }))
}
