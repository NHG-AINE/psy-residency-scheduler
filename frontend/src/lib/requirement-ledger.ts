import type { Source, Workbook } from './workbook'
import type { CatalogueEntry, ReviewStore } from './history-review'

export type LedgerMonth = {
  month: string; status: 'expected' | 'pending' | 'loa' | 'blank'; reasons: string[]
  requirement_id?: string; target?: CatalogueEntry
  evidence: { value: string | null; status: string; recorded_year: string | null; source: Source; resident_source: Source }[]
}
export type Requirement = {
  requirement_id: string; requirement_year: string; posting: string; required_months: number
  expected_months: number; remaining_months: number; evidence_status: 'not_evidenced' | 'partial' | 'supported'
  continuity_groups?: { institution: string; posting: string; start: string; end: string; expected_months: number }[]
}
export type ResidentLedger = {
  name: string | null; mcr: string | null; recorded_year: string | null; source: Source
  identity_safe: boolean; warnings: string[]; months: LedgerMonth[]; requirements: Requirement[]
  r1_routes: { requirement_ids: string[]; evidence_status: string }[]
}
export type RequirementLedger = {
  planning_start: string; cutoff: string; basis: 'projected_expected_not_certified'; residents: ResidentLedger[]
}

export async function evaluateRequirements(workbook: Workbook, store: ReviewStore, signal?: AbortSignal): Promise<RequirementLedger> {
  let response: Response
  try {
    response = await fetch('/api/requirement-ledger', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workbook, store }), signal })
  } catch {
    throw new Error('Could not reach the backend for requirements. Check the connection and retry.')
  }
  const data = await response.json().catch(() => null)
  if (!response.ok || !data || data.basis !== 'projected_expected_not_certified' || !Array.isArray(data.residents)
    || typeof data.cutoff !== 'string' || typeof data.planning_start !== 'string') {
    throw new Error(typeof data?.detail === 'string' ? data.detail : 'Requirements could not be loaded. Re-import the workbook or retry.')
  }
  return data as RequirementLedger
}

export type RequirementFilter = 'all' | 'completed' | 'missing'

export function visibleRequirements(ledger: ResidentLedger, filter: RequirementFilter): Requirement[] {
  const route = ledger.r1_routes.find((item) => item.evidence_status === 'supported')
  return ledger.requirements.filter((item) =>
    (item.requirement_year !== 'R1' || !route || route.requirement_ids.includes(item.requirement_id))
    && (filter === 'all' || (item.evidence_status === 'supported') === (filter === 'completed')))
}
