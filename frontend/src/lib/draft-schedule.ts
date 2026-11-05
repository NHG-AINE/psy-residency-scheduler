import { sameSource, sourceLabel, monthLabel } from './workbook.ts'
import type { Resident, Source, Workbook } from './workbook.ts'
import { reasonLabel, resolvedCatalogueTarget } from './history-review.ts'
import { postingHistoryEntry } from './posting-blocks.ts'
import type { HistoryEntry } from './history-review.ts'
import type { ReviewStore } from './history-review.ts'

export type DraftSchedule = {
  status: 'blocked' | 'infeasible' | 'unknown' | 'model_invalid' | 'feasible' | 'optimal'
  cutoff: string
  blockers: { code: string; source?: Source; sources?: Source[]; month?: string; name?: string }[]
  residents: { source: Source; name: string | null; mcr: string | null; route?: string
    months: { month: string; status: 'posting' | 'loa' | 'outside_draft_scope'; label: string | null; target?: { category: 'core' | 'elective' } | null }[]
    carryforward: { requirement_id: string; institution: string; months: number }[] }[]
  soft_results?: { distribution_deviation: number; ratio_deviation: number }
}

export async function generateDraft(workbook: Workbook, store: ReviewStore, signal: AbortSignal): Promise<DraftSchedule> {
  let response: Response
  try {
    response = await fetch('/api/draft', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workbook, store }), signal: AbortSignal.any([signal, AbortSignal.timeout(30_000)]) })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'TimeoutError') throw new Error('Draft generation timed out. Check the connection and retry.')
    throw new Error('Could not reach the backend to generate a draft. Check the connection and retry.')
  }
  const data = await response.json().catch(() => null)
  if (!response.ok || !data || !['blocked', 'infeasible', 'unknown', 'model_invalid', 'feasible', 'optimal'].includes(data.status)
    || !Array.isArray(data.residents) || !Array.isArray(data.blockers)) {
    throw new Error(typeof data?.detail === 'string' ? data.detail : 'Draft generation failed. Re-import the workbook or retry.')
  }
  return data as DraftSchedule
}

// Display copies only: source retains the location being replaced, never generated evidence.
// This overlay must never be passed to the history review or requirement ledger.
export function draftPostings(resident: Resident, draft: DraftSchedule | null): Resident['postings'] {
  const person = draft?.residents.find((candidate) => sameSource(candidate.source, resident.source))
  if (!person || !['optimal', 'feasible'].includes(draft!.status)) return resident.postings
  return resident.postings.map((posting) => {
    const month = person.months.find((candidate) => candidate.month === posting.month)
    return posting.status !== 'loa' && month?.status === 'posting' && month.label
      ? { ...posting, value: month.label, status: 'posting', draft: true, draftCategory: month.target?.category || 'core' } : posting
  })
}

// Display order only: recorded year first, then route within the R1 cohort.
export function groupDraftResidents(residents: Resident[], draft: DraftSchedule | null, entries?: HistoryEntry[]): Resident[] {
  const successfulDraft = draft && ['optimal', 'feasible'].includes(draft.status) ? draft : null
  if (!successfulDraft && !entries) return residents
  const routes = ['SGH', 'TTSH/NNI', 'NUH']
  return residents.map((resident) => {
    const years = [...new Set(Array.from((resident.residency_year || '').matchAll(/r\s*([1-5])\b/gi), (match) => match[1]))].sort().join(',') || 'unknown'
    const route = successfulDraft?.residents.find((person) => sameSource(person.source, resident.source))?.route
    const rank = routes.indexOf(route || '')
    const reasons = entries ? draftPostings(resident, successfulDraft).flatMap((posting) => {
      if (posting.status !== 'posting' || posting.draft) return []
      const entry = postingHistoryEntry(posting, entries)
      if (entry && resolvedCatalogueTarget(entry.review)) return []
      const codes = entry ? (entry.review.reasons.length ? entry.review.reasons : entry.match.reasons) : []
      return codes.length ? codes.map(reasonLabel) : ['No exact catalogue label']
    }) : []
    const unresolved = [...new Set(reasons)].sort((a, b) => a.localeCompare(b)).join('; ')
    return { resident, years, unresolved, rank: years === '1' && rank >= 0 ? rank : routes.length }
  }).sort((a, b) => {
    if (!!a.unresolved !== !!b.unresolved) return a.unresolved ? 1 : -1
    if (a.unresolved) return a.unresolved.localeCompare(b.unresolved)
    if (a.years === b.years) return a.rank - b.rank
    if (a.years === 'unknown') return 1
    if (b.years === 'unknown') return -1
    return a.years > b.years ? -1 : 1
  })
    .map((item) => item.resident)
}

export function updatedResidentCount(workbook: Workbook, draft: DraftSchedule): number {
  return workbook.residents.filter((resident) => draftPostings(resident, draft).some((posting) => posting.draft)).length
}

const blockerLabels: Record<string, string> = {
  no_schedulable_residents: 'No R1 or R2 residents in this planning year',
  conflicting_partial_r2_history: 'Review the partially completed R2 posting and institution',
  missing_r2_catalogue_option: 'No matching R2 catalogue option for the remaining requirement',
  unsupported_r2_remarks: 'Review unsupported R2 posting remarks',
  duplicate_r2_catalogue_option: 'Resolve duplicate R2 posting options',
  unsafe_identity: 'Resolve the resident identity in Issues',
  unresolved_history: 'Review unresolved historical postings', conflicting_month_evidence: 'Review conflicting records for this month',
  requirement_year_unconfirmed: 'Confirm the historical requirement year', programme_duration_mismatch: 'Correct the posting duration to match the programme',
  historical_progress_unknown: 'Review missing historical progress', pending_history_review: 'Review unresolved historical postings',
  conflicting_history: 'Review conflicting historical records', invalid_planning_month_evidence: 'Review conflicting planning month evidence',
  shared_capacity_outside_draft_scope: 'Review capacity shared with residents outside this draft',
  unsupported_r1_remarks: 'Review unsupported R1 posting remarks', duplicate_r1_catalogue_option: 'Resolve duplicate R1 posting options',
  invalid_capacity: 'Correct the posting capacity', invalid_duration: 'Correct the posting duration',
  unclear_intake: 'Review the unclear incoming intake', excess_intake: 'Review the excess incoming intake',
  duplicate_intake_placeholder: 'Resolve duplicate intake placeholders', intake_fill_blocked: 'Resolve intake issues before generating',
}
export function draftBlockerLabel(blocker: DraftSchedule['blockers'][number], workbook: Workbook): string {
  const sources = [...(blocker.sources || []), ...(blocker.source ? [blocker.source] : [])]
  const rows = [...new Set(sources.map((source) => sourceLabel(source.kind ? source : { sheet: source.sheet, row: source.row })))]
  const people = [...workbook.residents, ...workbook.histories.flatMap((history) => history.residents)]
  const names = [...new Set(people.filter((person) => sources.some((source) => sameSource(person.source, source))).map((person) => person.name || person.mcr).filter(Boolean))]
  return [blockerLabels[blocker.code] || blocker.code.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase()),
    ...names, ...rows, ...(blocker.month ? [monthLabel(blocker.month)] : [])].join(' - ')
}
