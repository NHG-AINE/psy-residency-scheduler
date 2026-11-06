import type { Source, Workbook } from './workbook'

export type CatalogueEntry = {
  key: string; signature: string; source: Source; category: 'core' | 'elective'
  residency_year: string | null; label: string
}
export type MonthValue = { month: string; value: string }
export type ResidentContext = { mcr: string; name: string; recorded_year: string; months: MonthValue[] }
export type Target = Pick<CatalogueEntry, 'key' | 'signature'>
export type ReviewDecision = {
  kind: 'resident'; context: ResidentContext; target: Target; requirement_year: string | null
} | {
  kind: 'alias'; context: { label: string; recorded_year: string; category: 'core' | 'elective' }; target: Target
}
export type ReviewStore = { version: 1; decisions: ReviewDecision[] }
export type DecisionState = { key: string; decision: ReviewDecision; target: CatalogueEntry | null; status: string; reasons: string[] }
export type HistoryEntry = {
  id: string; key: string; name: string | null; mcr: string | null; recorded_year: string | null; identity_safe: boolean
  months: MonthValue[]; sources: Source[]; context: ResidentContext
  match: { status: string; reasons: string[]; candidates: (CatalogueEntry & { year_context: string })[]; selected_candidate?: CatalogueEntry | null }
  review: { status: string; reasons: string[]; target: CatalogueEntry | null; requirement_year: string | null }
}
export type HistoryReview = { entries: HistoryEntry[]; catalogue: CatalogueEntry[]; decisions: DecisionState[] }
export const REVIEW_CHANGED = 'psy-review-changed'
export const STORAGE_KEY = 'psy-history-review-v1'
export const emptyStore = (): ReviewStore => ({ version: 1, decisions: [] })
const normalize = (value: string) => value.trim().replace(/\s+/g, ' ').toLowerCase()
const mcr = (value: string) => value.trim().replace(/\s+/g, ' ').toUpperCase()

export function decisionKey(decision: ReviewDecision): string {
  const context = decision.context
  return decision.kind === 'alias'
    ? JSON.stringify(['alias', normalize(decision.context.label), normalize(context.recorded_year), decision.context.category])
    : JSON.stringify(['resident', mcr(decision.context.mcr), decision.context.months.map((month) => [month.month, month.value]).sort((a, b) => a[0].localeCompare(b[0]))])
}

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const text = (value: unknown): value is string => typeof value === 'string' && value.length > 0 && value.length <= 2000
const fields = (value: Record<string, unknown>, allowed: string[]) => Object.keys(value).every((key) => allowed.includes(key))

export function parseReviewStore(raw: string): ReviewStore {
  let value: unknown
  try { value = JSON.parse(raw) } catch { throw new Error('Review data is not valid JSON. Choose an exported review file.') }
  if (!object(value) || value.version !== 1 || !fields(value, ['version', 'decisions']) || !Array.isArray(value.decisions) || value.decisions.length > 5000) {
    throw new Error('Unsupported review file. Expected version 1 and at most 5,000 decisions.')
  }
  for (const decision of value.decisions) {
    if (!object(decision) || !['resident', 'alias'].includes(String(decision.kind)) || !object(decision.context)
      || !object(decision.target) || !fields(decision.target, ['key', 'signature']) || !text(decision.target.key) || !text(decision.target.signature)
      || !fields(decision, decision.kind === 'resident' ? ['kind', 'context', 'target', 'requirement_year'] : ['kind', 'context', 'target'])) {
      throw new Error('A review decision has invalid or unexpected fields. Nothing was imported.')
    }
    const context = decision.context
    if (typeof context.recorded_year !== 'string' || context.recorded_year.length > 2000) throw new Error('A recorded-year scope is missing or invalid.')
    if (decision.kind === 'alias') {
      if (!fields(context, ['label', 'recorded_year', 'category']) || !text(context.label) || !['core', 'elective'].includes(String(context.category))) throw new Error('A shared label mapping has an invalid scope.')
    } else {
      if (!fields(context, ['mcr', 'name', 'recorded_year', 'months']) || !text(context.mcr) || !text(context.name)
        || !Array.isArray(context.months) || !context.months.length || context.months.length > 120
        || context.months.some((month) => !object(month) || !fields(month, ['month', 'value']) || !text(month.value) || typeof month.month !== 'string' || !/^\d{4}-(0[1-9]|1[0-2])$/.test(month.month))
        || !(decision.requirement_year === null || /^R[1-5]$/.test(String(decision.requirement_year)))) throw new Error('A resident decision has invalid identity, dates or requirement year.')
      const dates = context.months.map((month) => (month as MonthValue).month)
      if (new Set(dates).size !== dates.length) throw new Error('A resident decision repeats the same month.')
    }
  }
  const store = value as unknown as ReviewStore
  const seen = new Set<string>()
  for (const decision of store.decisions) {
    const key = decisionKey(decision)
    if (seen.has(key)) throw new Error('The review file contains duplicate or conflicting decisions for the same scope. Nothing was imported.')
    seen.add(key)
  }
  return store
}

export function mergeReviewStores(current: ReviewStore, incoming: ReviewStore): ReviewStore {
  const decisions = [...current.decisions]
  for (const next of incoming.decisions) {
    const prior = decisions.find((decision) => decisionKey(decision) === decisionKey(next))
    if (prior && JSON.stringify(prior) !== JSON.stringify(next)) {
      const scope = next.kind === 'alias' ? next.context.label : `${next.context.mcr}, ${next.context.months[0].month}`
      throw new Error(`Conflicting decision for ${scope}. Nothing was imported. Keep the saved decision, or remove it below before importing its replacement.`)
    }
    if (!prior) decisions.push(next)
  }
  if (decisions.length > 5000) throw new Error('The combined review data exceeds 5,000 decisions. Nothing was imported.')
  return { version: 1, decisions }
}

export function readReviewStore(storage: Pick<Storage, 'getItem'>): { store: ReviewStore; error: string } {
  try {
    const raw = storage.getItem(STORAGE_KEY)
    return { store: raw ? parseReviewStore(raw) : emptyStore(), error: '' }
  } catch (error) {
    return { store: emptyStore(), error: `Saved review data could not be read. ${error instanceof Error ? error.message : 'Browser storage is unavailable.'}` }
  }
}

export function writeReviewStore(storage: Pick<Storage, 'setItem'>, store: ReviewStore): void {
  parseReviewStore(JSON.stringify(store))
  try { storage.setItem(STORAGE_KEY, JSON.stringify(store)) } catch {
    throw new Error('The browser could not save review data. Storage may be full or disabled. The decision was not saved. Your previous decisions are unchanged. Retry from the review form when storage is available.')
  }
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(REVIEW_CHANGED))
}

export async function evaluateHistory(workbook: Workbook, store: ReviewStore, signal?: AbortSignal, scope: 'history' | 'timetable' = 'history'): Promise<HistoryReview> {
  let response: Response
  try { response = await fetch('/api/history-review', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workbook, store, scope }), signal }) } catch {
    throw new Error('Could not reach the backend for history review. Check the connection and retry.')
  }
  const data = await response.json().catch(() => null)
  if (!response.ok || !data || ![data.entries, data.catalogue, data.decisions].every(Array.isArray)) {
    throw new Error(typeof data?.detail === 'string' ? data.detail : 'History review failed. Re-import the workbook or retry.')
  }
  return data as HistoryReview
}

export const reviewReasons: Record<string, string> = {
  explicit_elective: 'Explicit elective label', mixed_recorded_years: 'Recorded R-years do not identify one preferred match',
  recorded_year_unknown: 'Recorded R-year missing', catalogue_year_unknown: 'Catalogue year missing', mixed_catalogue_years: 'More than one catalogue requirement year',
  core_elective_ambiguity: 'Could be core or elective', requirement_year_review: 'Catalogue year differs from recorded R-year',
  catalogue_alternatives: 'Other catalogue alternatives retained',
  earlier_year_fallback: 'Recognized in an earlier catalogue year',
  no_catalogue_match: 'No exact catalogue label', multiple_catalogue_candidates: 'Several catalogue matches',
  remediation_credit_review: 'Remediation posting',
  no_earlier_year_context: 'No earlier residency year is available for remediation matching',
  conflicting_saved_decisions: 'Saved decisions conflict', catalogue_target_changed_or_missing: 'Catalogue target changed or is missing',
  incompatible_requirement_year: 'Requirement year does not match the chosen catalogue entry', incompatible_alias_category: 'Mapping category differs from the catalogue entry',
  explicit_elective_target_required: 'An explicit elective label requires an elective target',
  identity_review_required: 'Resolve the resident identity in Issues first', recorded_context_changed: 'Recorded identity or R-year context changed',
  recorded_period_changed: 'Saved resident decision overlaps a changed or incomplete period',
  not_present_in_this_import: 'Not present in this import',
}
export const reasonLabel = (reason: string) => reviewReasons[reason] || reason.replaceAll('_', ' ')

export function historyStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    unreviewed: 'Needs review', automatic_match: 'Automatically matched',
    label_confirmed: 'Label confirmed - year open', reviewed: 'Label and year confirmed',
    needs_review: 'Saved decision needs review', credit_review_required: 'Remediation recognised',
  }
  return labels[status] || status.replaceAll('_', ' ')
}

export function resolvedCatalogueTarget(review: HistoryEntry['review']): CatalogueEntry | null {
  return ['automatic_match', 'reviewed', 'label_confirmed', 'credit_review_required'].includes(review.status) ? review.target : null
}

export function matchesHistoryFilter(entry: HistoryEntry, filter: string, query: string): boolean {
  const status = entry.review.status
  const labelResolved = !!resolvedCatalogueTarget(entry.review)
  return (filter === 'all' || (filter === 'reviewed' ? status === 'reviewed' : !labelResolved))
    && `${entry.name || ''} ${entry.mcr || ''} ${entry.months[0].value}`.toLowerCase().includes(query.trim().toLowerCase())
}
