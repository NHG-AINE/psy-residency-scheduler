import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import { evaluateRequirements, visibleRequirements } from '../src/lib/requirement-ledger.ts'
import type { ReviewStore } from '../src/lib/history-review.ts'
import type { ResidentLedger } from '../src/lib/requirement-ledger.ts'
import type { Workbook } from '../src/lib/workbook.ts'

const person = (): ResidentLedger => ({
  name: 'Alex Example', mcr: 'M001', recorded_year: 'R3', source: { sheet: 'Planning', row: 3 }, identity_safe: true, warnings: [],
  months: [{ month: '2026-01', status: 'expected', requirement_id: 'r3.continuity_clinic', reasons: [],
    evidence: [{ value: 'IMH Continuity Clinic', status: 'posting', recorded_year: 'R3', source: { sheet: 'Earlier', row: 3, column: 'C' }, resident_source: { sheet: 'Earlier', row: 3 } }] },
    { month: '2026-02', status: 'pending', reasons: ['requirement_year_unconfirmed'], evidence: [{ value: 'Original wording', status: 'posting', recorded_year: 'R3', source: { sheet: 'Earlier', row: 3, column: 'D' }, resident_source: { sheet: 'Earlier', row: 3 } }] }],
  requirements: [
    { requirement_id: 'r1.general_medicine', requirement_year: 'R1', posting: 'General Medicine', required_months: 4, expected_months: 0, remaining_months: 4, evidence_status: 'not_evidenced' },
    { requirement_id: 'r1.neurology', requirement_year: 'R1', posting: 'Neurology', required_months: 2, expected_months: 0, remaining_months: 2, evidence_status: 'not_evidenced' },
    { requirement_id: 'r1.medicine_neurology', requirement_year: 'R1', posting: 'Medicine & Neurology', required_months: 6, expected_months: 6, remaining_months: 0, evidence_status: 'supported' },
    { requirement_id: 'r1.inpatient_psychiatry', requirement_year: 'R1', posting: 'Inpatient Psychiatry', required_months: 6, expected_months: 6, remaining_months: 0, evidence_status: 'supported' },
    { requirement_id: 'r3.continuity_clinic', requirement_year: 'R3', posting: 'Continuity Clinic', required_months: 12, expected_months: 6, remaining_months: 6, evidence_status: 'partial', continuity_groups: [{ institution: 'IMH', posting: 'Continuity Clinic', start: '2025-07', end: '2025-12', expected_months: 6 }, { institution: 'TTSH', posting: 'Continuity Clinic', start: '2026-07', end: '2026-12', expected_months: 6 }] },
    { requirement_id: 'r5.elective', requirement_year: 'R5', posting: 'Elective', required_months: 6, expected_months: 0, remaining_months: 6, evidence_status: 'not_evidenced' },
  ],
  r1_routes: [{ requirement_ids: ['r1.general_medicine', 'r1.neurology', 'r1.inpatient_psychiatry'], evidence_status: 'partial' }, { requirement_ids: ['r1.medicine_neurology', 'r1.inpatient_psychiatry'], evidence_status: 'supported' }],
})

test('Requirements renders one concise table, missing highlights and pending records only when present', async () => {
  // Vite transforms the existing TSX for server rendering; no listening server or DOM dependency.
  const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  try {
    const { default: Loader, RequirementContent } = await vite.ssrLoadModule('/src/components/ResidentRequirements.tsx')
    const html = renderToStaticMarkup(createElement(RequirementContent, { ledger: person(), cutoff: '2027-06', planningStart: '2027-07', onHistoryReview: () => {} }))
    assert.match(html, /Months through Jun 2027 - Planning 2027\/28/)
    assert.equal((html.match(/<table>/g) || []).length, 1)
    assert.match(html, />Counted</)
    assert.doesNotMatch(html, /Monthly evidence|>Status<|longest same-posting|General Medicine|>Neurology</)
    assert.equal((html.match(/>Inpatient Psychiatry</g) || []).length, 1)
    assert.match(html, /class="requirement-missing"/)
    assert.match(html, /Earlier.*D3/)
    assert.match(html, /Open History review/)
    assert.match(html, /option value="all" selected=""/)
    const empty = person(); empty.months = []; empty.r1_routes.forEach((route) => { route.evidence_status = 'not_evidenced' }); empty.requirements.forEach((item) => { item.expected_months = 0; item.remaining_months = item.required_months; item.evidence_status = 'not_evidenced' })
    const noHistory = renderToStaticMarkup(createElement(RequirementContent, { ledger: empty, cutoff: '2027-06', planningStart: '2027-07', onHistoryReview: () => {} }))
    assert.match(noHistory, /No safely matched history before this planning period/)
    assert.doesNotMatch(noHistory, /Unknown/)
    assert.match(noHistory, /General Medicine.*?<td>4<\/td><td>0<\/td><td>4<\/td>/)
    assert.match(noHistory, /General Medicine/)
    assert.match(noHistory, /Alternative: combined route/)
    assert.doesNotMatch(noHistory, /Pending records|Show pending records|Open History review/)
    const unsafe = person(); unsafe.identity_safe = false; unsafe.warnings = ['unsafe_identity']
    const blocked = renderToStaticMarkup(createElement(RequirementContent, { ledger: unsafe, cutoff: '2026-06', planningStart: '2026-07', onHistoryReview: () => {} }))
    assert.match(blocked, /identity issues are resolved/)
    assert.doesNotMatch(blocked, /<table/)
    const loading = renderToStaticMarkup(createElement(Loader, { resident: {}, workbook: {}, onHistoryReview: () => {} }))
    assert.match(loading, /aria-busy="true"/)
    assert.match(loading, /Loading requirements/)
    assert.match(loading, /requirements-table/)
    assert.doesNotMatch(loading, /resident-column/)
  } finally { await vite.close() }
})

test('client sends each supplied workbook and store with cancellation and actionable failures', async () => {
  const original = globalThis.fetch
  const controller = new AbortController()
  const requests: { body: unknown; signal: AbortSignal | null | undefined }[] = []
  globalThis.fetch = async (_input, init) => {
    requests.push({ body: JSON.parse(String(init?.body)), signal: init?.signal })
    return new Response(JSON.stringify({ basis: 'projected_expected_not_certified', cutoff: '2027-06', planning_start: '2027-07', residents: [] }))
  }
  try {
    const workbook = { target_year: 2027 } as Workbook
    const initial = { version: 1 as const, decisions: [] }
    await evaluateRequirements(workbook, initial, controller.signal)
    const nextWorkbook = { target_year: 2026 } as Workbook
    await evaluateRequirements(nextWorkbook, initial, controller.signal)
    const saved: ReviewStore = { version: 1, decisions: [{ kind: 'alias', context: { label: 'Old wording', recorded_year: 'R3', category: 'core' }, target: { key: 'stable-content', signature: 'catalogue-content' } }] }
    await evaluateRequirements(nextWorkbook, saved, controller.signal)
    assert.deepEqual(requests.map((request) => request.body), [{ workbook, store: initial }, { workbook: nextWorkbook, store: initial }, { workbook: nextWorkbook, store: saved }])
    assert.equal(requests[0].signal, controller.signal)
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Import the workbook again for the selected planning year.' }), { status: 422 })
    await assert.rejects(evaluateRequirements(workbook, initial), /selected planning year/)
    globalThis.fetch = async () => { throw new Error('offline') }
    await assert.rejects(evaluateRequirements(workbook, initial), /Check the connection and retry/)
  } finally { globalThis.fetch = original }
})

test('requirement filters exclude the unused R1 route and distinguish completed from missing', () => {
  const resident = person()
  assert.deepEqual(visibleRequirements(resident, 'completed').map((row) => row.requirement_id), ['r1.medicine_neurology', 'r1.inpatient_psychiatry'])
  assert.deepEqual(visibleRequirements(resident, 'missing').map((row) => row.requirement_id), ['r3.continuity_clinic', 'r5.elective'])
  assert.equal(visibleRequirements(resident, 'all').length, 4)
  resident.r1_routes.forEach((route) => { route.evidence_status = 'partial' })
  assert.equal(visibleRequirements(resident, 'all').length, 6)
  assert.equal(visibleRequirements(resident, 'missing').length, 4)
  resident.requirements.forEach((row) => { row.evidence_status = 'supported' })
  assert.deepEqual(visibleRequirements(resident, 'missing'), [])
})
