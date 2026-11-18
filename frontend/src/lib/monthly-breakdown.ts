import type { Workbook } from './workbook.ts'
import { sameSource } from './workbook.ts'
import { resolvedCatalogueTarget } from './history-review.ts'
import type { CapacityOverflow, DraftSchedule } from './draft-schedule.ts'
import type { HistoryEntry } from './history-review.ts'
import { draftPostings, draftResidentYear } from './draft-schedule.ts'
import { postingCategory, postingDisplay, postingHistoryEntry } from './posting-blocks.ts'

type Counts = Record<string, number>
export type BreakdownGroup = { key: string; label: string; counts: Counts; institutions: {
  label: string; counts: Counts; allCounts: Counts; overflows: CapacityOverflow[]
}[] }

const programmeYears = (value?: string | null): string[] => value?.toUpperCase().match(/\bR[1-5]\b/g) || []

export function monthlyBreakdown(workbook: Workbook, draft: DraftSchedule | null, entries: HistoryEntry[], year = '') {
  const groupElectives = year === 'R2' || year === 'R5'
  const groups = new Map<string, BreakdownGroup>()
  const eligibleSites = new Set<BreakdownGroup['institutions'][number]>()
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
      site = { label: rowLabel, counts: {}, allCounts: {}, overflows: [] }
      group.institutions.push(site)
    }
    return { group, site }
  }
  for (const row of workbook.postings.core) {
    if (row.posting && (!year || programmeYears(row.residency_year).includes(year))) {
      eligibleSites.add(siteFor(row.posting, 'core').site)
    }
  }
  for (const row of workbook.postings.electives || []) {
    if (!year || programmeYears(row.residency_year).includes(year)) {
      eligibleSites.add(siteFor(`${row.institution} ${row.elective}`, 'elective').site)
    }
  }
  const increment = (counts: Counts, month: string) => { counts[month] = (counts[month] || 0) + 1 }
  const months = new Set(workbook.months.map((month) => month.month))
  for (const resident of workbook.residents) {
    const planned = draft?.residents.find((person) => sameSource(person.source, resident.source))
    const cohortYears = programmeYears(draftResidentYear(resident, draft))
    for (const posting of draftPostings(resident, draft)) {
      if (!months.has(posting.month)) continue
      const display = postingDisplay([posting], 'catalogue', entries)
      const displayCategory = postingCategory(display, posting.status)
      if (displayCategory === 'requirements_completed') continue
      const recognised = displayCategory === 'core' || displayCategory === 'elective'
      const entry = recognised && !posting.draft ? postingHistoryEntry(posting, entries) : undefined
      const draftTarget = recognised && posting.draft ? planned?.months.find((month) => month.month === posting.month)?.target : null
      const target = entry ? resolvedCatalogueTarget(entry.review) : draftTarget
      const targetYears = [...new Set(programmeYears(target?.residency_year))]
      const cohortMatches = targetYears.filter((candidate) => cohortYears.includes(candidate))
      const reviewedYear = programmeYears(entry?.review.requirement_year)[0]
      const requirementYear = reviewedYear || (targetYears.length === 1 ? targetYears[0] : cohortMatches.length === 1 ? cohortMatches[0] : undefined)
      // Older drafts can lack a target year. An ambiguous catalogue target still needs review.
      const legacyDraft = posting.draft && !targetYears.length
      const category = recognised && !requirementYear && !legacyDraft ? 'unresolved' : displayCategory
      if (category === 'core' || category === 'elective') {
        const { group, site } = siteFor(display.label, category)
        increment(site.allCounts, posting.month)
        if (!year || (requirementYear || cohortYears[0]) === year) {
          increment(group.counts, posting.month); increment(site.counts, posting.month)
          for (const overflow of draft?.capacity_overflows || []) {
            if (overflow.month === posting.month && overflow.category === category && overflow.label === display.label
              && overflow.residency_year === requirementYear
              && (!draftTarget?.requirement_id || draftTarget.requirement_id === overflow.requirement_id)
              && (!target?.source || (sameSource(target.source, overflow.source) && target.source.column === overflow.source.column))
              && !site.overflows.includes(overflow)) site.overflows.push(overflow)
          }
        }
      } else if (!year || cohortYears[0] === year) {
        const label = category === 'loa' ? 'LOA' : category === 'unallocated' ? 'Unallocated' : 'Unresolved'
        increment(groupFor(label, category).counts, posting.month)
      }
    }
  }
  const r1Order = ['General Medicine', 'Neurology', 'Medicine & Neurology', 'Inpatient Psychiatry']
  const rank = (group: BreakdownGroup) => year === 'R1' && r1Order.includes(group.label) ? r1Order.indexOf(group.label) : r1Order.length
  return [...groups.values()].filter((group) => Object.keys(group.counts).length)
    .sort((a, b) => rank(a) - rank(b) || Number(!a.institutions.length) - Number(!b.institutions.length) || a.label.localeCompare(b.label))
    .map((group) => ({ ...group, institutions: group.institutions
      .filter((site) => eligibleSites.has(site) || Object.keys(site.counts).length)
      .sort((a, b) => a.label.localeCompare(b.label)) }))
}
