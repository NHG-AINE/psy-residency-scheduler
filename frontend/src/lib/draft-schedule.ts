import { sameSource, sourceLabel, monthLabel } from './workbook.ts'
import type { Resident, Source, Workbook } from './workbook.ts'
import { reasonLabel, resolvedCatalogueTarget } from './history-review.ts'
import { postingHistoryEntry } from './posting-blocks.ts'
import type { HistoryEntry } from './history-review.ts'
import type { ReviewStore } from './history-review.ts'
import type { SavedDraft } from './workbook-session.ts'

export type RequestOutcome = {
  request: { posting_request: string | null; period: string | null; source: Source }
  status: 'met' | 'not_met' | 'pending'; reason?: string | null; reason_code?: string; duplicate_of?: number
  alternatives?: RequestOutcome[]
  requested_months?: number
  requested_durations?: number[]
  assigned?: { label: string; months: string[] }[]; matched_months?: string[]; replacement_months?: string[]
  capacity?: CapacityRow[]
}
type CapacityRow = {
  month: string; requirement_id: string; institution: string; label: string; source: Source
  residency_year: string; category: 'core' | 'elective'; max: number; assigned: number
}
export type CapacityOverflow = CapacityRow & {
  residents: { name: string | null; mcr: string | null; source: Source }[]
}
type ResidentWarning = { source: Source; name: string | null; mcr: string | null; reasons: DraftSchedule['blockers'] }
export type DraftEditOption = {
  posting: string; institution: string; residency_year: string; label: string; source: Source; category: 'core' | 'elective'; requirement_id: string
}
export type DraftCarryforward = {
  requirement_id: string; institution: string; months: number; label?: string
  block_start?: string | null; training_start?: number
}
export type DraftSchedule = {
  capacity_overflows?: CapacityOverflow[]
  capacity_coverage_notes?: { code: string; source: Source }[]
  status: 'blocked' | 'infeasible' | 'unknown' | 'model_invalid' | 'feasible' | 'optimal' | 'edited'
  finished_early?: boolean
  edit_options?: DraftEditOption[]
  edit_baseline?: unknown
  edit_warnings?: DraftChangeIssue[]
  cutoff: string
  blockers: { code: string; source?: Source; sources?: Source[]; month?: string; name?: string; clusters?: string[] }[]
  skipped_residents?: ResidentWarning[]
  historical_cluster_warnings?: ResidentWarning[]
  residents: { source: Source; name: string | null; mcr: string | null; route?: string; projected_year?: string; recorded_year?: string
    requests?: RequestOutcome[]
    months: { month: string; status: 'posting' | 'loa' | 'outside_draft_scope' | 'requirements_completed'; label: string | null; block_start?: string; target?: { category: 'core' | 'elective'; residency_year?: string; source?: Source; requirement_id?: string; institution?: string } | null }[]
    carryforward: DraftCarryforward[] }[]
  soft_priority?: string[]
  wall_time_seconds?: number
  optimisation_stages?: { priority: string; status: string; wall_time_seconds: number }[]
  soft_results?: { distribution_deviation: number; ratio_deviation: number }
}

export type DraftInsertionSide = 'before' | 'after'
export type DraftChange = { resident: Source; start: string } & (
  { kind: 'edit'; posting: string; institution: string; offering: Source } | { kind: 'swap'; destination: string } |
  { kind: 'insert'; destination: string; side: DraftInsertionSide })
export type DraftChangeIssue = { severity: 'hard' | 'soft'; code: string; message: string; affected: { source: Source; month: string }[] }
export type DraftChangeResult = { draft: DraftSchedule | null; issues: DraftChangeIssue[] }

export function draftSwapOutcome(result: DraftChangeResult) {
  if (!result.draft || result.issues.some((issue) => issue.severity === 'hard')) return 'blocked'
  return result.issues.length ? 'warning' : 'clean'
}

type DraftMonths = DraftSchedule['residents'][number]['months']

export function draftContinuation(months: DraftMonths, carryforward: DraftCarryforward[], start: string) {
  const explicit = carryforward.filter((row) => row.block_start === start)
  if (explicit.length) return { months: explicit.length === 1 ? explicit[0].months : 0, ambiguous: explicit.length !== 1 }
  const block = months.filter((month) => month?.block_start === start)
  const last = months.findLast((month) => month?.status === 'posting')
  const target = last?.target
  if (!target || last.block_start !== start) return { months: 0, ambiguous: false }
  const matches = carryforward.filter((row) => row.block_start === undefined && row.requirement_id === target.requirement_id
    && row.institution === target.institution && (row.label === undefined || row.label === last.label))
  if (!matches.length) return { months: 0, ambiguous: false }
  if (target.requirement_id === 'r1.general_medicine') {
    if (matches[0] !== carryforward.find((row) => row.requirement_id.startsWith('r1.'))) return { months: 0, ambiguous: false }
    if (block.length === 1 && matches[0].months > 1 && carryforward.some((row) => row.requirement_id === 'r1.neurology')) {
      return { months: 0, ambiguous: true }
    }
  }
  if (target.requirement_id?.startsWith('r5.')) {
    if (target.requirement_id === 'r5.child_geriatric_psychiatry' && matches.length === 1 && block.length + matches[0].months <= 6) {
      return { months: matches[0].months, ambiguous: false }
    }
    const partial = matches.filter((row) => row.months !== 3 && row.months !== 6 && block.length + row.months <= 6)
    if (partial.length === 1) return { months: partial[0].months, ambiguous: false }
    if (!partial.length && matches.every((row) => block.length + row.months > 6)) return { months: 0, ambiguous: false }
    return { months: 0, ambiguous: true }
  }
  return { months: matches.length === 1 ? matches[0].months : 0, ambiguous: matches.length !== 1 }
}

export function draftContinuationText(months: number) {
  return months ? `Continues for ${months} training month${months === 1 ? '' : 's'} next year` : ''
}

function movedLayout(months: DraftMonths, start: string, destination: string,
  carryforward: DraftCarryforward[], side?: DraftInsertionSide) {
  const blocks = months.map((month) => month?.status === 'posting' ? month.block_start : undefined)
  const from = blocks.indexOf(start)
  const target = blocks.indexOf(destination)
  if (from < 0 || target < 0 || from === target) return null
  const first = Math.min(from, target)
  const last = Math.max(blocks.lastIndexOf(start), blocks.lastIndexOf(destination))
  if (months.slice(first, last + 1).some((month) => month.status !== 'posting' && month.status !== 'loa')) return null
  const training = blocks.slice(first, last + 1).flatMap((block) => block ? [block] : [])
  const order = [...new Set(training)]
  const lengths = new Map<string, number>()
  for (const block of order) {
    const tail = draftContinuation(months, carryforward, block)
    if (tail.ambiguous) return null
    lengths.set(block, training.filter((key) => key === block).length + tail.months)
  }
  const fromBlock = order.indexOf(start)
  const toBlock = order.indexOf(destination)
  if (side) {
    order.splice(fromBlock, 1)
    order.splice(order.indexOf(destination) + Number(side === 'after'), 0, start)
  } else {
    if (lengths.get(start) !== lengths.get(destination)) return null
    order[fromBlock] = destination
    order[toBlock] = start
  }
  const reordered = order.flatMap((block) => Array<string>(lengths.get(block)!).fill(block))
  const changed = training.some((block, index) => reordered[index] !== block)
  let index = 0
  for (let month = first; month <= last; month++) {
    if (blocks[month]) blocks[month] = reordered[index++]
  }
  return { blocks, changed }
}

export function draftSwapLayout(months: DraftMonths, start: string, destination: string, carryforward: DraftCarryforward[] = []) {
  return movedLayout(months, start, destination, carryforward)?.blocks ?? null
}

export function draftInsertion(months: DraftMonths, start: string, destination: string,
  side: DraftInsertionSide, carryforward: DraftCarryforward[] = []) {
  return movedLayout(months, start, destination, carryforward, side)
}

export function draftDropEdges(months: DraftMonths, start: string, destination: string,
  carryforward: DraftCarryforward[] = []): [number, number] {
  if (draftSwapLayout(months, start, destination, carryforward)) {
    const nearSide = start < destination ? 'before' : 'after'
    if (draftInsertion(months, start, destination, nearSide, carryforward)?.changed === false) {
      return nearSide === 'before' ? [0.1, 0.3] : [0.3, 0.1]
    }
  }
  return [0.3, 0.3]
}

export function draftPreviewIssuesForRow(issues: DraftChangeIssue[], resident: Source, from?: Source, destination?: Source) {
  if (!from || sameSource(resident, from)) return issues
  return sameSource(resident, destination) ? issues.filter((issue) => issue.code === 'invalid_destination') : []
}

export function draftPostingChoices(options: DraftEditOption[], years: string) {
  const eligibleYears = new Set(years.toUpperCase().match(/\bR[1-5]\b/g))
  const postings = new Map<string, DraftEditOption[]>()
  for (const option of options) {
    if (!option.posting || !option.institution || !option.residency_year.toUpperCase().match(/\bR[1-5]\b/g)?.some((year) => eligibleYears.has(year))) continue
    const key = JSON.stringify([option.posting, option.category])
    const group = postings.get(key) ?? []
    group.push(option)
    postings.set(key, group)
  }
  return [...postings.entries()].map(([key, offers]) => {
    const { posting, category } = offers[0]
    const distinct = postings.has(JSON.stringify([posting, category === 'core' ? 'elective' : 'core']))
    return { key, label: distinct ? `${posting} (${category})` : posting,
      offers: [...offers].sort((a, b) => a.institution.localeCompare(b.institution) || a.residency_year.localeCompare(b.residency_year)) }
  }).sort((a, b) => a.label.localeCompare(b.label))
}

export function isUsableDraft(draft: DraftSchedule | null | undefined): draft is DraftSchedule {
  return !!draft && ['optimal', 'feasible', 'edited'].includes(draft.status)
}

export type DraftResult = { saved: SavedDraft | null; failure: DraftSchedule | null }

export function settleDraftAttempt(current: DraftResult, attempt: SavedDraft, operation: { cancelled: boolean; invalidated: boolean }): DraftResult {
  if (operation.cancelled || operation.invalidated) return current
  if (attempt.data.status === 'optimal' || attempt.data.status === 'feasible') return { saved: attempt, failure: null }
  return { saved: current.saved, failure: attempt.data }
}

export function requestSummary(resident: Resident, draft: DraftSchedule | null) {
  const rows = isUsableDraft(draft)
    ? draft.residents.find((person) => sameSource(person.source, resident.source))?.requests?.filter((row) => row.duplicate_of === undefined) || [] : []
  const counts = { met: 0, not_met: 0, pending: 0 }
  for (const row of rows) counts[row.status]++
  const indicator = (month: string) => rows.find((row) => row.matched_months?.includes(month)) || rows.find((row) => row.replacement_months?.includes(month))
  return { rows, counts, indicator }
}

export type RequestStatus = RequestOutcome['status']

export function requestTotals(draft: DraftSchedule | null) {
  const counts = { met: 0, not_met: 0, pending: 0 }
  if (isUsableDraft(draft)) {
    for (const person of draft.residents) {
      for (const row of person.requests || []) {
        if (row.duplicate_of === undefined) counts[row.status]++
      }
    }
  }
  return counts
}

export function filterRequestResidents(residents: Resident[], draft: DraftSchedule | null, status: RequestStatus | null) {
  if (!status || !isUsableDraft(draft)) return residents
  return residents.filter((resident) => requestSummary(resident, draft).counts[status] > 0)
}

export function canGenerateDraft(workbook: Workbook | null, selectedYear = workbook?.target_year, importing = false): boolean {
  return !importing && !!workbook && workbook.target_year === selectedYear && workbook.target_year === Math.max(...workbook.available_years.map(({ year }) => year))
}

// Allow an extra minute beyond the selected solver budget for preparation and transport.
const DRAFT_REQUEST_OVERHEAD_MS = 60_000
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

export async function checkDraftReady(token: string, signal: AbortSignal): Promise<boolean> {
  const response = await fetch(`/api/draft/${encodeURIComponent(token)}/status`, {
    signal: AbortSignal.any([signal, AbortSignal.timeout(DRAFT_CONTROL_TIMEOUT_MS)]),
  })
  return response.ok && (await response.json()).ready === true
}

export async function finishDraft(token: string, signal: AbortSignal): Promise<void> {
  const response = await fetch(`/api/draft/${encodeURIComponent(token)}/finish`, {
    method: 'POST', signal: AbortSignal.any([signal, AbortSignal.timeout(DRAFT_CONTROL_TIMEOUT_MS)]),
  })
  if (!response.ok) throw new Error('Could not use the current draft. Check the connection and retry.')
}

export async function generateDraft(workbook: Workbook, store: ReviewStore, signal: AbortSignal, token?: string, maxSeconds = 120): Promise<DraftSchedule> {
  let response: Response
  try {
    response = await fetch(token ? `/api/draft?token=${encodeURIComponent(token)}` : '/api/draft', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workbook, store, max_seconds: maxSeconds }), signal: AbortSignal.any([signal, AbortSignal.timeout(maxSeconds * 1000 + DRAFT_REQUEST_OVERHEAD_MS)]) })
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

export async function validateDraftChange(workbook: Workbook, store: ReviewStore, draft: DraftSchedule, change: DraftChange,
  signal: AbortSignal, original?: DraftSchedule | null): Promise<DraftChangeResult> {
  async function check(baseline?: DraftSchedule) {
    const baseline_residents = baseline?.residents.map(({ source, route, months, carryforward }) => ({ source, route, months, carryforward }))
    const response = await fetch('/api/draft/validate-change', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workbook, store, draft, change, baseline_residents }),
      signal: AbortSignal.any([signal, AbortSignal.timeout(baseline ? 60_000 : 40_000)]),
    })
    return { response, data: await response.json().catch(() => null) }
  }
  let { response, data } = await check()
  if (response.status === 422 && data?.detail?.code === 'draft_warning_baseline_required'
    && original && original !== draft && !signal.aborted) {
    ({ response, data } = await check(original))
  }
  if (!response.ok || !Array.isArray(data?.issues) || (data.draft !== null && (data.draft?.status !== 'edited' || !Array.isArray(data.draft.residents)))) {
    const message = typeof data?.detail === 'string' ? data.detail : data?.detail?.message
    throw new Error(typeof message === 'string' ? message : 'Could not check this change. Try again.')
  }
  return data
}

// Display copies only: source retains the location being replaced, never generated evidence.
// This overlay must never be passed to the history review or requirement ledger.
export function draftPostings(resident: Resident, draft: DraftSchedule | null): Resident['postings'] {
  if (!isUsableDraft(draft)) return resident.postings
  const person = draft.residents.find((candidate) => sameSource(candidate.source, resident.source))
  const unresolved = draft.skipped_residents?.find((candidate) => sameSource(candidate.source, resident.source))
    ?.reasons.some((reason) => ['unresolved_history', 'pending_history_review'].includes(reason.code))
  if (!person) return unresolved ? resident.postings.map((posting) => posting.status === 'blank'
    ? { ...posting, unresolvedDraft: true } : posting) : resident.postings
  return resident.postings.map((posting) => {
    const month = person.months.find((candidate) => candidate.month === posting.month)
    if (posting.status === 'blank' && month?.status === 'requirements_completed') {
      return { ...posting, status: 'requirements_completed' }
    }
    return posting.status !== 'loa' && month?.status === 'posting' && month.label
      ? { ...posting, value: month.label, status: 'posting', draft: true, draftCategory: month.target?.category || 'core', draftBlockStart: month.block_start } : posting
  })
}

export function draftResidentYear(resident: Resident, draft: DraftSchedule | null) {
  const projected = isUsableDraft(draft)
    ? draft.residents.find((person) => sameSource(person.source, resident.source))?.projected_year
    : null
  return projected ?? resident.residency_year
}

// Display order only: draft cohort first, then route within the R1 cohort.
export function groupDraftResidents(residents: Resident[], draft: DraftSchedule | null, entries?: HistoryEntry[]): Resident[] {
  const successfulDraft = isUsableDraft(draft) ? draft : null
  if (!successfulDraft && !entries) return residents
  const routes = ['SGH', 'TTSH/NNI', 'NUH']
  return residents.map((resident) => {
    const years = [...new Set(Array.from((draftResidentYear(resident, successfulDraft) || '').matchAll(/r\s*([1-5])\b/gi), (match) => match[1]))].sort().join(',') || 'unknown'
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

const blockerLabels: Record<string, string> = {
  unresolved_occupied_posting: 'Resolve the occupied posting label and requirement before counting capacity',
  conflicting_occupied_posting: 'Resolve conflicting posting evidence for the same resident and month',
  unresolved_retained_posting: 'Resolve the retained posting label and requirement before counting capacity',
  conditional_retained_posting: 'Review the retained posting; its occupied place is outside the confirmed capacity counts',
  no_schedulable_residents: 'No R1–R5 residents have usable scheduling inputs',
  conflicting_partial_r5_history: 'Review the interrupted or conflicting R5 posting history',
  missing_r5_catalogue_option: 'No supported R5 catalogue option for the remaining requirement',
  duplicate_r5_catalogue_option: 'Resolve duplicate R5 posting options',
  conflicting_partial_r4_history: 'Review the interrupted or conflicting R4 posting history',
  missing_r4_catalogue_option: 'No matching R4 catalogue option for the remaining requirement',
  completed_r4_missing_clusters: 'Review completed R4 history with missing cluster coverage',
  historical_cluster_gap: 'Completed R1-R4 with missing cluster coverage',
  unsupported_r4_remarks: 'Review unsupported R4 posting remarks',
  duplicate_r4_catalogue_option: 'Resolve duplicate R4 posting options',
  r4_schedule_infeasible: 'No valid R4 schedule was found; review eligibility, clusters and outstanding training',
  r4_cluster_review: 'Review cluster coverage alongside posting eligibility and outstanding training',
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
    const dates = monthRanges(months)
    return { reason, sources, dates }
  })
}


export function groupedCapacityRows(rows: CapacityRow[]) {
  const groups = new Map<string, { key: string; label: string; source: Source; periods: { start: string; end: string; assigned: number; max: number }[] }>()
  const ordinal = (month: string) => Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7))
  for (const row of [...rows].sort((a, b) => a.month.localeCompare(b.month))) {
    const key = JSON.stringify([row.requirement_id, row.residency_year, row.category, row.institution, row.label, row.source.sheet, row.source.row, row.source.column])
    let group = groups.get(key)
    if (!group) {
      group = { key, label: `${row.residency_year} - ${row.label}`, source: row.source, periods: [] }
      groups.set(key, group)
    }
    const last = group.periods.at(-1)
    if (last && ordinal(row.month) === ordinal(last.end) + 1 && last.assigned === row.assigned && last.max === row.max) last.end = row.month
    else group.periods.push({ start: row.month, end: row.month, assigned: row.assigned, max: row.max })
  }
  return [...groups.values()].sort((a, b) => a.label.localeCompare(b.label))
}

export function monthRanges(months: string[]) {
  const ranges: string[][] = []
  const ordinal = (month: string) => Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7))
  for (const month of [...new Set(months)].sort()) {
    const last = ranges.at(-1)
    if (last && ordinal(month) === ordinal(last.at(-1)!) + 1) last.push(month)
    else ranges.push([month])
  }
  return ranges.map((range) => range.length === 1 ? monthLabel(range[0])
    : `${monthLabel(range[0])} \u2013 ${monthLabel(range.at(-1)!)}`).join(', ')
}
