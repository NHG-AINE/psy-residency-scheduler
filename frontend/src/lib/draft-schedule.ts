import { sameSource, sourceLabel, monthLabel } from './workbook.ts'
import type { Resident, Source, Workbook } from './workbook.ts'
import { reasonLabel, resolvedCatalogueTarget } from './history-review.ts'
import { postingHistoryEntry } from './posting-blocks.ts'
import type { HistoryEntry } from './history-review.ts'
import type { ReviewStore } from './history-review.ts'

export type RequestOutcome = {
  request: { posting_request: string | null; period: string | null; source: Source }
  status: 'met' | 'not_met' | 'pending'; reason?: string | null; reason_code?: string; duplicate_of?: number
  assigned?: { label: string; months: string[] }[]; matched_months?: string[]; replacement_months?: string[]
}
export type DraftSchedule = {
  status: 'blocked' | 'infeasible' | 'unknown' | 'model_invalid' | 'feasible' | 'optimal'
  cutoff: string
  blockers: { code: string; source?: Source; sources?: Source[]; month?: string; name?: string; clusters?: string[] }[]
  skipped_residents?: { source: Source; name: string | null; mcr: string | null; reasons: DraftSchedule['blockers'] }[]
  residents: { source: Source; name: string | null; mcr: string | null; route?: string
    requests?: RequestOutcome[]
    months: { month: string; status: 'posting' | 'loa' | 'outside_draft_scope'; label: string | null; target?: { category: 'core' | 'elective'; residency_year?: string } | null }[]
    carryforward: { requirement_id: string; institution: string; months: number }[] }[]
  soft_priority?: string[]
  wall_time_seconds?: number
  optimisation_stages?: { priority: string; status: string; wall_time_seconds: number }[]
  soft_results?: { distribution_deviation: number; ratio_deviation: number }
}

export function requestSummary(resident: Resident, draft: DraftSchedule | null) {
  const rows = draft && ['optimal', 'feasible'].includes(draft.status)
    ? draft.residents.find((person) => sameSource(person.source, resident.source))?.requests?.filter((row) => row.duplicate_of === undefined) || [] : []
  const counts = { met: 0, not_met: 0, pending: 0 }
  for (const row of rows) counts[row.status]++
  const indicator = (month: string) => rows.find((row) => row.matched_months?.includes(month)) || rows.find((row) => row.replacement_months?.includes(month))
  return { rows, counts, indicator }
}

export type RequestStatus = RequestOutcome['status']

export function requestTotals(draft: DraftSchedule | null) {
  const counts = { met: 0, not_met: 0, pending: 0 }
  if (draft && ['optimal', 'feasible'].includes(draft.status)) {
    for (const person of draft.residents) {
      for (const row of person.requests || []) {
        if (row.duplicate_of === undefined) counts[row.status]++
      }
    }
  }
  return counts
}

export function filterRequestResidents(residents: Resident[], draft: DraftSchedule | null, status: RequestStatus | null) {
  if (!status || !draft || !['optimal', 'feasible'].includes(draft.status)) return residents
  return residents.filter((resident) => requestSummary(resident, draft).counts[status] > 0)
}

export function canGenerateDraft(workbook: Workbook | null, selectedYear = workbook?.target_year, importing = false): boolean {
  return !importing && !!workbook && workbook.target_year === selectedYear && workbook.target_year === Math.max(...workbook.available_years.map(({ year }) => year))
}

// Allow an extra minute beyond the two-minute solver budget for preparation and transport.
const DRAFT_REQUEST_TIMEOUT_MS = 180_000
const DRAFT_CONTROL_TIMEOUT_MS = 15_000

export async function startDraft(): Promise<string> {
  const response = await fetch('/api/draft/start', { method: 'POST', signal: AbortSignal.timeout(DRAFT_CONTROL_TIMEOUT_MS) })
  const data = await response.json().catch(() => null)
  if (!response.ok || typeof data?.token !== 'string') throw new Error('Could not start draft generation. Check the connection and retry.')
  return data.token
}

export async function cancelDraft(token: string): Promise<void> {
  const response = await fetch(`/api/draft/${encodeURIComponent(token)}`, { method: 'DELETE', signal: AbortSignal.timeout(DRAFT_CONTROL_TIMEOUT_MS) })
  if (!response.ok) throw new Error('Could not cancel draft generation. Check the connection and retry.')
}

export async function generateDraft(workbook: Workbook, store: ReviewStore, signal: AbortSignal, token?: string): Promise<DraftSchedule> {
  let response: Response
  try {
    response = await fetch(token ? `/api/draft?token=${encodeURIComponent(token)}` : '/api/draft', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workbook, store }), signal: AbortSignal.any([signal, AbortSignal.timeout(DRAFT_REQUEST_TIMEOUT_MS)]) })
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
  if (!draft || !['optimal', 'feasible'].includes(draft.status)) return resident.postings
  const person = draft.residents.find((candidate) => sameSource(candidate.source, resident.source))
  const unresolved = draft.skipped_residents?.find((candidate) => sameSource(candidate.source, resident.source))
    ?.reasons.some((reason) => ['unresolved_history', 'pending_history_review'].includes(reason.code))
  if (!person) return unresolved ? resident.postings.map((posting) => posting.status === 'blank'
    ? { ...posting, unresolvedDraft: true } : posting) : resident.postings
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
      if (posting.unresolvedDraft) return ['Review unresolved historical postings']
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
  no_schedulable_residents: 'No R1–R5 residents have usable scheduling inputs',
  conflicting_partial_r5_history: 'Review the interrupted or conflicting R5 posting history',
  missing_r5_catalogue_option: 'No supported R5 catalogue option for the remaining requirement',
  duplicate_r5_catalogue_option: 'Resolve duplicate R5 posting options',
  conflicting_partial_r4_history: 'Review the interrupted or conflicting R4 posting history',
  missing_r4_catalogue_option: 'No matching R4 catalogue option for the remaining requirement',
  completed_r4_missing_clusters: 'Review completed R4 history with missing cluster coverage',
  unsupported_r4_remarks: 'Review unsupported R4 posting remarks',
  duplicate_r4_catalogue_option: 'Resolve duplicate R4 posting options',
  r4_schedule_infeasible: 'No valid R4 schedule was found; review eligibility, clusters and capacity',
  r4_cluster_review: 'Review cluster coverage alongside posting eligibility and capacity',
  conflicting_partial_r3_history: 'Review the interrupted or conflicting Continuity Clinic history',
  missing_r3_catalogue_option: 'No matching Continuity Clinic catalogue option',
  unsupported_r3_remarks: 'Review unsupported R3 posting remarks',
  duplicate_r3_catalogue_option: 'Resolve duplicate R3 posting options',
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
    ...names, ...rows, ...(blocker.clusters?.length ? [blocker.clusters.join(", ")] : []), ...(blocker.month ? [monthLabel(blocker.month)] : [])].join(' - ')
}

// Each skipped resident is already identified by its planning-sheet source.
export function groupedDraftWarnings(reasons: DraftSchedule['blockers']) {
  const groups = new Map<string, { reason: string; sources: string[]; months: string[] }>()
  for (const blocker of reasons) {
    const sources = [...new Set([...(blocker.sources || []), ...(blocker.source ? [blocker.source] : [])]
      .map((source) => sourceLabel(source.kind ? source : { sheet: source.sheet, row: source.row })))].sort()
    const key = JSON.stringify([blocker.code, sources, blocker.clusters, !!blocker.month])
    let group = groups.get(key)
    if (!group) {
      const reason = blockerLabels[blocker.code] || blocker.code.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
      group = { reason: [reason, ...(blocker.clusters?.length ? [blocker.clusters.join(', ')] : [])].join(' - '), sources, months: [] }
      groups.set(key, group)
    }
    if (blocker.month) group.months.push(blocker.month)
  }
  return [...groups.values()].map(({ reason, sources, months }) => {
    const ranges: string[][] = []
    const ordinal = (month: string) => Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7))
    for (const month of [...new Set(months)].sort()) {
      const last = ranges.at(-1)
      if (last && ordinal(month) === ordinal(last.at(-1)!) + 1) last.push(month)
      else ranges.push([month])
    }
    const dates = ranges.map((range) => range.length === 1 ? monthLabel(range[0])
      : `${monthLabel(range[0])} \u2013 ${monthLabel(range.at(-1)!)}`).join(', ')
    return { reason, sources, dates }
  })
}
