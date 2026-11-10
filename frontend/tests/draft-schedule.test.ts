import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import { canGenerateDraft, cancelDraft, startDraft, draftBlockerLabel, draftPostings, generateDraft, groupDraftResidents, groupedDraftWarnings, requestSummary, updatedResidentCount } from '../src/lib/draft-schedule.ts'
import type { HistoryEntry } from '../src/lib/history-review.ts'
import type { DraftSchedule } from '../src/lib/draft-schedule.ts'
import { groupPostings, postingCategory, postingDisplay } from '../src/lib/posting-blocks.ts'
import type { Resident, Workbook } from '../src/lib/workbook.ts'

const resident: Resident = {
  name: 'Example', mcr: 'SYN001', residency_year: 'R1,R2', intake: '2026', mom_number: null, email: null, remarks: null,
  source: { sheet: 'Timetable', row: 3 },
  postings: ['posting', 'loa', 'posting', 'blank'].map((status, index) => ({ month: `2027-${7 + index}`.replace('-7', '-07').replace('-8', '-08').replace('-9', '-09'), status: status as 'posting' | 'loa' | 'blank', value: index === 1 ? 'LOA' : 'IMH Inpatient Psychiatry', source: { sheet: 'Timetable', row: 3, column: String(index) } })),
}
const draft: DraftSchedule = {
  status: 'feasible', cutoff: '2027-06', blockers: [], residents: [{ source: resident.source, name: resident.name, mcr: resident.mcr, carryforward: [],
    months: resident.postings.map((posting, index) => ({ month: posting.month, status: index === 2 ? 'outside_draft_scope' : 'posting', label: 'IMH Inpatient Psychiatry' })) }],
}

test('overlay changes only solver posting months, preserves evidence and discard restores original cells', () => {
  const other = { ...resident, source: { sheet: 'Timetable', row: 4 } }
  const placeholder = { ...resident, source: { kind: 'intake_placeholder' as const, slot_id: '2027-01' } }
  const workbook = { residents: [resident, other, placeholder], histories: ['original'], requests: ['original'] } as unknown as Workbook
  const before = structuredClone(workbook)
  const postings = draftPostings(resident, draft)
  assert.equal(postings[0].draft, true)
  assert.equal(postings[3].draft, true)
  assert.equal(postings[1], resident.postings[1])
  assert.equal(postings[2], resident.postings[2])
  assert.equal(draftPostings(other, draft), other.postings)
  assert.equal(draftPostings(placeholder, draft), placeholder.postings)
  assert.equal(updatedResidentCount(workbook, draft), 1)
  assert.deepEqual(workbook, before)
  assert.equal(draftPostings(resident, null), resident.postings)
  assert.equal(draftPostings(resident, { ...draft, status: 'blocked' }), resident.postings)
  const blocks = groupPostings(postings)
  assert.equal(blocks.length, 4, 'equal imported and draft labels retain their provenance boundary')
  assert.equal(postingCategory(postingDisplay(blocks[0]), 'posting'), 'core')
  assert.equal(postingCategory(postingDisplay(blocks[2]), 'posting'), 'unresolved')
})

test('generated intake slots match only their synthetic identity and blockers retain readable evidence context', () => {
  const first = { ...resident, source: { kind: 'intake_placeholder' as const, slot_id: '2027-01' } }
  const second = { ...resident, source: { kind: 'intake_placeholder' as const, slot_id: '2027-02' } }
  const slotDraft = { ...draft, residents: [{ ...draft.residents[0], source: first.source }] }
  assert.equal(draftPostings(first, slotDraft)[0].draft, true)
  assert.equal(draftPostings(second, slotDraft), second.postings)
  const workbook = { residents: [resident], histories: [] } as unknown as Workbook
  const label = draftBlockerLabel({ code: 'conflicting_month_evidence', sources: [resident.postings[0].source, resident.postings[1].source], month: '2027-07' }, workbook)
  assert.match(label, /Review conflicting records for this month/)
  assert.match(label, /Example/)
  assert.equal(label.split('Timetable').length - 1, 1, 'repeated cell sources collapse to one row reference')
})

test('draft request sends the original workbook, saved decisions and cancellation signal and reports backend failures', async (context) => {
  const controller = new AbortController()
  const workbook = { target_year: 2028 } as Workbook
  const store = { version: 1 as const, decisions: [] }
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(url, '/api/draft')
    assert.deepEqual(JSON.parse(String(options.body)), { workbook, store })
    assert.ok(options.signal instanceof AbortSignal)
    controller.abort()
    assert.equal(options.signal.aborted, true)
    return new Response(JSON.stringify(draft))
  })
  assert.deepEqual(await generateDraft(workbook, store, controller.signal), draft)
  context.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ detail: 'Review inputs first.' }), { status: 422 }))
  await assert.rejects(generateDraft(workbook, store, controller.signal), /Review inputs first/)
  context.mock.method(globalThis, 'fetch', async () => new Response('invalid json'))
  await assert.rejects(generateDraft(workbook, store, controller.signal), /Draft generation failed/)
})


test('draft groups recorded years before R1 routes, preserving ties and original data', () => {
  const years = ['R1', 'R2', 'R1', 'R1', 'R1', 'R1', 'R1,R2', 'R3', 'R2,R3', null, 'R5', 'R4']
  const people: Resident[] = years.map((year, index) => ({ ...resident, residency_year: year, name: `Resident ${index}`, source: { sheet: 'Timetable', row: index + 1 } }))
  people[3] = { ...people[3], source: { kind: 'intake_placeholder', slot_id: '2027-01' } }
  const routes = ['NUH', undefined, 'TTSH/NNI', 'SGH', 'SGH', 'Unknown', 'SGH']
  const result = { ...draft, residents: people.flatMap((person, index) => routes[index] ? [{ ...draft.residents[0], source: person.source, route: routes[index] }] : []) }
  const before = structuredClone({ people, result })
  assert.deepEqual(groupDraftResidents(people, result), [10, 11, 7, 8, 1, 6, 3, 4, 2, 0, 5, 9].map((index) => people[index]))
  assert.deepEqual(groupDraftResidents([people[0], people[1], people[2], people[6]], result), [people[1], people[6], people[2], people[0]])
  assert.deepEqual({ people, result }, before)
})

test('no successful draft preserves workbook order', () => {
  const people = [resident, { ...resident, source: { sheet: 'Timetable', row: 4 } }]
  assert.equal(groupDraftResidents(people, null), people)
  for (const status of ['blocked', 'infeasible', 'unknown', 'model_invalid'] as const) {
    assert.equal(groupDraftResidents(people, { ...draft, status }), people)
  }
})


test('unresolved labels sort last by readable reason groups, excluding LOA, blank and generated months', () => {
  const people: Resident[] = Array.from({ length: 6 }, (_, index) => ({ ...resident, residency_year: 'R1', source: { sheet: 'Timetable', row: index + 1 },
    postings: [{ ...resident.postings[0], source: { sheet: 'Timetable', row: index + 1, column: 'B' } }] }))
  people[2].postings[0].status = 'loa'
  people[3].postings[0].status = 'blank'
  const entry = (index: number, reasons: string[]): HistoryEntry => ({
    months: [{ month: people[index].postings[0].month, value: people[index].postings[0].value! }], sources: [people[index].postings[0].source],
    match: { reasons, status: 'unmatched', candidates: [] }, review: { reasons, status: 'unreviewed', target: null, requirement_year: null },
  } as HistoryEntry)
  const entries = [entry(0, ['multiple_catalogue_candidates']), entry(1, ['no_catalogue_match']), entry(4, ['no_catalogue_match']), entry(5, ['multiple_catalogue_candidates', 'no_catalogue_match'])]
  assert.deepEqual(groupDraftResidents(people, null, entries), [2, 3, 1, 4, 5, 0].map((index) => people[index]))
  const generated = { ...draft, residents: [{ ...draft.residents[0], source: people[0].source, route: 'SGH' }] }
  assert.equal(groupDraftResidents(people, generated, entries)[0], people[0])
  entries[0].review = { ...entries[0].review, status: 'reviewed', target: { key: 'confirmed' } as NonNullable<HistoryEntry['review']['target']> }
  assert.equal(groupDraftResidents(people, null, entries)[0], people[0])
})


test('R2 elective display retains exact labels and separates matching core labels', () => {
  const result = structuredClone(draft)
  result.residents[0].months = resident.postings.map((posting, index) => ({
    month: posting.month, status: 'posting', label: 'IMH Addiction Medicine',
    target: { category: index === 3 ? 'elective' : 'core' },
  }))
  const postings = draftPostings(resident, result)
  const blocks = groupPostings(postings)
  assert.equal(blocks.length, 4)
  const display = postingDisplay(blocks[3])
  assert.equal(display.label, 'IMH Addiction Medicine')
  assert.deepEqual(display.markers, ['Elective'])
  assert.equal(postingCategory(display, 'posting'), 'elective')
  assert.equal(postingCategory(postingDisplay(blocks[2]), 'posting'), 'core')
  assert.equal(postings[1], resident.postings[1], 'LOA remains unchanged')
})


test('skipped resident warnings combine consecutive months without merging reasons, sources or gaps', () => {
  const source = { sheet: 'History', row: 18 }
  const reasons = ['2027-02', '2026-12', '2027-01', '2027-02', '2027-04'].map((month, index) => ({
    code: 'unresolved_history', source: { ...source, column: String(index) }, month,
  }))
  const groups = groupedDraftWarnings([...reasons,
    { code: 'conflicting_history', source, month: '2027-01' },
    { code: 'unresolved_history', source: { ...source, row: 19 }, month: '2027-01' },
    { code: 'unresolved_history', source },
  ])
  assert.equal(groups.length, 4)
  assert.equal(groups[0].dates, 'Dec 26 \u2013 Feb 27, Apr 27')
  assert.deepEqual(groups[0].sources, ['History \u00b7 row 18'])
  assert.equal(groups[1].reason, 'Review conflicting historical records')
  assert.deepEqual(groups[2].sources, ['History \u00b7 row 19'])
  assert.equal(groups[3].dates, '')
  assert.equal(reasons.length, 5)
})


test('unresolved skipped history marks only blank draft cells and discard restores them', () => {
  const skipped = { ...draft, residents: [], skipped_residents: [{ source: resident.source, name: resident.name, mcr: resident.mcr,
    reasons: [{ code: 'unresolved_history' }] }] }
  const cells = draftPostings(resident, skipped)
  assert.equal(postingCategory(postingDisplay([cells[3]]), cells[3].status), 'unresolved')
  assert.equal(postingDisplay([cells[3]]).label, 'Unresolved')
  assert.equal(cells[0], resident.postings[0])
  assert.equal(cells[1], resident.postings[1])
  assert.equal(draftPostings(resident, null), resident.postings)
  assert.equal(draftPostings(resident, { ...skipped, skipped_residents: [] }), resident.postings)
})


test('draft generation is restricted to the latest workbook year, independent of list order', () => {
  const workbook = { target_year: 2027, available_years: [{ year: 2028 }, { year: 2026 }, { year: 2027 }] } as Workbook
  assert.equal(canGenerateDraft(workbook), false)
  assert.equal(canGenerateDraft({ ...workbook, target_year: 2028 }), true)
  assert.equal(canGenerateDraft({ ...workbook, target_year: 2029 }), false)
  assert.equal(canGenerateDraft(null), false)
})

test('generation controls follow the selected year immediately during navigation', () => {
  const workbook = { target_year: 2027, available_years: [{ year: 2026 }, { year: 2027 }] } as Workbook
  assert.equal(canGenerateDraft(workbook, 2027), true)
  assert.equal(canGenerateDraft(workbook, 2026), false)
  assert.equal(canGenerateDraft(workbook, 2027, true), false)
})

test('draft cancellation uses the registered operation and reports failures', async (context) => {
  const calls: string[] = []
  context.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    calls.push(`${options.method} ${url}`)
    return new Response(JSON.stringify({ token: 'operation' }))
  })
  const token = await startDraft()
  await cancelDraft(token)
  assert.deepEqual(calls, ['POST /api/draft/start', 'DELETE /api/draft/operation'])
  context.mock.method(globalThis, 'fetch', async () => new Response('', { status: 503 }))
  await assert.rejects(cancelDraft(token), /Could not cancel/)
})


test('request summaries and markers share draft outcomes and exclude duplicates', () => {
  const request = { posting_request: 'IMH Example', period: null, source: { sheet: 'Request', row: 2 } }
  const rows = [
    { request, status: 'met' as const, matched_months: ['2027-07'] },
    { request, status: 'not_met' as const, replacement_months: ['2027-10'], reason: 'R4 Inpatient must be outside IMH.', reason_code: 'r1_imh_exclusion' },
    { request, status: 'pending' as const, reason: 'Clarify' },
    { request, status: 'met' as const, duplicate_of: 0, matched_months: ['2027-07'] },
  ]
  const withRequests = { ...draft, residents: [{ ...draft.residents[0], requests: rows }] }
  const summary = requestSummary(resident, withRequests)
  assert.deepEqual(summary.counts, { met: 1, not_met: 1, pending: 1 })
  assert.equal(summary.indicator('2027-07')?.status, 'met')
  assert.equal(summary.indicator('2027-10')?.status, 'not_met')
  assert.equal(summary.indicator('2027-10')?.reason, 'R4 Inpatient must be outside IMH.')
  assert.equal(summary.indicator('2027-08'), undefined)
  assert.deepEqual(requestSummary(resident, null).counts, { met: 0, not_met: 0, pending: 0 })
})


test('request details show the outcome reason without workbook row metadata', async () => {
  const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
  try {
    const { default: RequestDetails } = await vite.ssrLoadModule('/src/components/RequestDetails.tsx')
    const html = renderToStaticMarkup(createElement(RequestDetails, {
      name: 'Example', hint: 'Request details', className: 'request-indicator', children: 'Details',
      rows: [{ request: { posting_request: 'IMH Inpatient Psychiatry', period: null, source: { sheet: 'Request', row: 37 } },
        status: 'not_met', reason: 'R4 Inpatient must be outside IMH.',
        assigned: [{ label: 'SGH Inpatient Psychiatry', months: ['2028-04'] }] }],
    }))
    assert.match(html, /Why this wasn&#x27;t met/)
    assert.match(html, /R4 Inpatient must be outside IMH/)
    assert.match(html, /SGH Inpatient Psychiatry/)
    assert.doesNotMatch(html, /row 37/)
  } finally {
    await vite.close()
  }
})
