import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import { canGenerateDraft, cancelDraft, startDraft, draftBlockerLabel, draftContinuation, draftDropEdges, draftInsertion, draftPostings, draftPostingChoices, draftPreviewIssuesForRow, draftResidentYear, draftSwapLayout, draftSwapOutcome, generateDraft, groupDraftResidents, groupedDraftWarnings, groupedCapacityRows, requestSummary, requestTotals, filterRequestResidents, settleDraftAttempt } from '../src/lib/draft-schedule.ts'
import type { SavedDraft } from '../src/lib/workbook-session.ts'
import type { HistoryEntry } from '../src/lib/history-review.ts'
import type { DraftEditOption, DraftSchedule } from '../src/lib/draft-schedule.ts'
import { groupPostings, postingCategory, postingDisplay } from '../src/lib/posting-blocks.ts'
import { monthlyBreakdown } from '../src/lib/monthly-breakdown.ts'
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

test('drop layouts compare full training months and leave future-only assignments outside the preview', () => {
  const march = '2028-03', june = '2028-06'
  const geriatric = { category: 'core' as const, requirement_id: 'r2.geriatric_psychiatry', institution: 'NUH' }
  const elective = { category: 'elective' as const, requirement_id: 'r2.elective', institution: 'NUH' }
  const months: DraftSchedule['residents'][number]['months'] = [
    ...['03', '04', '05'].map((month) => ({ month: `2028-${month}`, block_start: march, status: 'posting' as const, label: 'Geriatric', target: geriatric })),
    { month: june, block_start: june, status: 'posting', label: 'Women’s Health', target: elective },
  ]
  const future = { requirement_id: 'r2.elective', institution: 'NUH', label: 'Women’s Health', months: 2 }
  const expected = [june, june, june, march]
  for (const rows of [[future], [{ ...future, block_start: june }]]) {
    assert.deepEqual(draftSwapLayout(months, june, march, rows), expected)
    assert.deepEqual(draftInsertion(months, june, march, 'before', rows), { blocks: expected, changed: true })
  }
  assert.equal(draftSwapLayout(months, june, march, [{ ...future, block_start: null, training_start: 10 }]), null)

  const legacy = { ...future, requirement_id: 'r5.elective', months: 3 }
  const longer = months.map((month) => ({ ...month, block_start: march, target: { ...elective, requirement_id: 'r5.elective' }, label: legacy.label })).slice(0, 3)
  assert.deepEqual(draftContinuation(longer, [legacy], march), { months: 0, ambiguous: true })
  for (const remaining of [4, 5]) {
    assert.deepEqual(draftContinuation(longer.slice(0, 6 - remaining), [{ ...legacy, months: remaining }], march),
      { months: remaining, ambiguous: false })
  }
  const combined = { ...legacy, requirement_id: 'r5.child_geriatric_psychiatry' }
  assert.deepEqual(draftContinuation(longer.map((month) => ({ ...month, target: { ...elective, requirement_id: combined.requirement_id } })),
    [combined], march), { months: 3, ambiguous: false })
})

test('editor choices combine recorded years, separate core from elective, and retain offering cells', () => {
  const offer = (year: string, posting: string, category: DraftEditOption['category'], institution: string, column: string): DraftEditOption => ({
    residency_year: year, posting, institution, category, label: `${institution} ${posting}`, requirement_id: 'synthetic', source: { sheet: 'Postings', row: 4, column },
  })
  const r2Core = offer('R2', 'Addiction Medicine', 'core', 'IMH', 'B')
  const r2Elective = offer('R2', 'Addiction Medicine', 'elective', 'IMH', 'D')
  const r3 = offer('R3', 'Continuity Clinic', 'core', 'NUH', 'F')
  const r4 = offer('R4', 'Forensic Psychiatry', 'core', 'IMH', 'H')
  const choices = draftPostingChoices([r4, r3, r2Elective, r2Core], 'R2;R3')
  assert.deepEqual(choices.map(({ label, offers }) => [label, offers.map((option) => option.source)]), [
    ['Addiction Medicine (core)', [r2Core.source]], ['Addiction Medicine (elective)', [r2Elective.source]], ['Continuity Clinic', [r3.source]],
  ])
})

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
  assert.deepEqual(workbook, before)
  assert.equal(draftPostings(resident, null), resident.postings)
  assert.equal(draftPostings(resident, { ...draft, status: 'blocked' }), resident.postings)
  const blocks = groupPostings(postings)
  assert.equal(blocks.length, 4, 'equal imported and draft labels retain their provenance boundary')
  assert.equal(postingCategory(postingDisplay(blocks[0]), 'posting'), 'core')
  assert.equal(postingCategory(postingDisplay(blocks[2]), 'posting'), 'unresolved')
})

test('requirements completion overlays only blank cells and stays outside monthly posting counts', () => {
  const before = structuredClone(resident)
  const completed: DraftSchedule = { ...draft, residents: [{ ...draft.residents[0], months: resident.postings.map((posting, index) => ({
    month: posting.month, status: index === 0 ? 'outside_draft_scope' : 'requirements_completed', label: null,
  })) }] }
  const cells = draftPostings(resident, completed)
  assert.deepEqual(cells.slice(0, 3), resident.postings.slice(0, 3))
  const status = cells[3].status
  assert.equal(status, 'requirements_completed')
  const display = postingDisplay([cells[3]])
  assert.equal(display.label, 'Requirements completed')
  assert.equal(postingCategory(display, status), 'requirements_completed')
  const workbook = { residents: [resident], months: resident.postings.map(({ month }) => ({ month })),
    postings: { core: [], electives: [] } } as unknown as Workbook
  assert.ok(monthlyBreakdown(workbook, completed, []).every((group) => !group.counts[cells[3].month]))
  assert.deepEqual(resident, before)
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
    assert.deepEqual(JSON.parse(String(options.body)), { workbook, store, max_seconds: 600 })
    assert.ok(options.signal instanceof AbortSignal)
    controller.abort()
    assert.equal(options.signal.aborted, true)
    return new Response(JSON.stringify(draft))
  })
  const timeout = context.mock.method(AbortSignal, 'timeout', () => new AbortController().signal)
  assert.deepEqual(await generateDraft(workbook, store, controller.signal, undefined, 600), draft)
  assert.equal(timeout.mock.calls[0].arguments[0], 660_000)
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

test('projected R-years sort and filter catch-up and advanced months without changing recorded labels', () => {
  const advancing: Resident = { ...resident, residency_year: 'R4' }
  const peer: Resident = { ...advancing, source: { sheet: 'Timetable', row: 8 } }
  const projection: DraftSchedule = { ...draft, residents: [{ ...draft.residents[0], projected_year: 'R4,R5',
    months: [
      { month: advancing.postings[0].month, status: 'posting', label: 'TTSH Continuity Clinic', target: { category: 'core', residency_year: 'R3' } },
      { month: advancing.postings[3].month, status: 'posting', label: 'IMH ANDS', target: { category: 'elective', residency_year: 'R5' } },
    ],
  }] }
  assert.equal(draftResidentYear(advancing, projection), 'R4,R5')
  assert.equal(draftResidentYear(advancing, null), 'R4')
  assert.equal(draftResidentYear(advancing, { ...projection, status: 'infeasible' }), 'R4')
  assert.equal(advancing.residency_year, 'R4')
  assert.deepEqual(groupDraftResidents([peer, advancing], projection), [advancing, peer])
  assert.deepEqual(groupDraftResidents([peer, advancing], null), [peer, advancing])
  const workbook = { residents: [advancing], months: advancing.postings.map(({ month }) => ({ month })),
    postings: { core: [], electives: [] } } as unknown as Workbook
  assert.equal(monthlyBreakdown(workbook, projection, [], 'R3').find((group) => group.label === 'Continuity Clinic')?.counts[advancing.postings[0].month], 1)
  assert.equal(monthlyBreakdown(workbook, projection, [], 'R5').find((group) => group.label === 'Electives')?.counts[advancing.postings[3].month], 1)
  assert.deepEqual(monthlyBreakdown(workbook, null, [], 'R5'), [])
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


test('alternative outcomes count once and mark only the selected months', () => {
  const request = { posting_request: 'Option A', period: null, source: { sheet: 'Requests', row: 2 } }
  const alternatives = [
    { request, status: 'not_met' as const, replacement_months: ['2028-01'] },
    { request: { ...request, posting_request: 'Option B' }, status: 'met' as const, matched_months: ['2028-04'] },
  ]
  const group = { request, status: 'met' as const, alternatives, matched_months: ['2028-04'], replacement_months: [] }
  const groupedDraft: DraftSchedule = { ...draft, residents: [{ ...draft.residents[0], requests: [group] }] }
  assert.deepEqual(requestTotals(groupedDraft), { met: 1, not_met: 0, pending: 0 })
  assert.equal(requestSummary(resident, groupedDraft).indicator('2028-01'), undefined)
  assert.equal(requestSummary(resident, groupedDraft).indicator('2028-04')?.status, 'met')
  assert.deepEqual(filterRequestResidents([resident], groupedDraft, 'not_met'), [])
  groupedDraft.residents[0].requests = [{ ...group, status: 'not_met', matched_months: [], replacement_months: ['2028-01'] }]
  assert.deepEqual(requestTotals(groupedDraft), { met: 0, not_met: 1, pending: 0 })
  assert.equal(filterRequestResidents([resident], groupedDraft, 'not_met').length, 1)
})


test('draft feedback shows historical warnings and request outcomes with the relevant details', async () => {
  const vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  try {
    const { default: DraftReview } = await vite.ssrLoadModule('/src/components/DraftReview.tsx')
    const workbook: Workbook = { target_year: 2027, target_sheet: 'Timetable', available_years: [{ year: 2027, sheet: 'Timetable' }],
      residents: [resident], months: [], histories: [], requests: [], warnings: [], postings: { core: [], rows: [] } }
    const reviewProps = { draft, workbook, yearLabel: 'Jul 2027 – Jun 2028', onFind: () => {} }
    assert.match(renderToStaticMarkup(createElement(DraftReview, reviewProps)), /No draft warnings/)
    const warnings = renderToStaticMarkup(createElement(DraftReview, {
      ...reviewProps, draft: { ...draft, historical_cluster_warnings: [{ name: 'Example', mcr: null, source: resident.source,
        reasons: [{ code: 'historical_cluster_gap', source: resident.source, clusters: ['SHS'], month: '2027-08' }] }],
      skipped_residents: [{ ...resident, reasons: [{ code: 'unresolved_history' }] }],
      capacity_overflows: [{ month: '2027-08', requirement_id: 'r4.forensic', residency_year: 'R4', institution: 'IMH',
        label: 'IMH Forensic Psychiatry', max: 5, assigned: 7, source: { sheet: 'Postings', row: 30 }, residents: [] }],
      capacity_coverage_notes: ['B', 'C'].map((column) => ({ code: 'unresolved_occupied_posting', source: { sheet: 'Timetable', row: 3, column } })),
      },
    }))
    assert.match(warnings, /4 warning groups/)
    assert.match(warnings, /Historical cluster warnings.*1 resident/)
    assert.match(warnings, /<strong>Example<\/strong>/)
    assert.match(warnings, /Completed R1-R4 with missing cluster coverage - SHS.*Aug 27/)
    assert.match(warnings, /Source: Timetable \u00b7 row 3/)
    assert.match(warnings, /Capacity counts need review.*1 record excluded/)
    assert.match(warnings, /Timetable \u00b7 B3; Timetable \u00b7 C3/)
    assert.match(warnings, /7 assigned \/ 5 max/)
    assert.match(warnings, /Find in timetable/)
    const { default: RequestDetails } = await vite.ssrLoadModule('/src/components/RequestDetails.tsx')
    const { default: RequestOutcomeFilter } = await vite.ssrLoadModule('/src/components/RequestOutcomeFilter.tsx')
    for (const [selected, label] of [['not_met', 'Not met'], ['pending', 'Pending']]) {
      const emptyFilter = renderToStaticMarkup(createElement(RequestOutcomeFilter, {
        draft, selected, onChange: () => {}, disabled: false,
      }))
      assert.ok(emptyFilter.includes(`<option value="${selected}" selected="">${label} (0)</option>`))
    }
    const row = { request: { posting_request: 'IMH Inpatient Psychiatry', period: null, source: { sheet: 'Request', row: 37 } },
      status: 'not_met', reason: 'R4 Inpatient must be outside IMH.',
      assigned: [{ label: 'SGH Inpatient Psychiatry', months: ['2028-04'] }] }
    const props = { name: 'Example', hint: 'Request details', className: 'request-indicator', rows: [row] }
    const html = renderToStaticMarkup(createElement(RequestDetails, props, 'Details'))
    assert.match(html, /Why this wasn&#x27;t met/)
    assert.match(html, /R4 Inpatient must be outside IMH/)
    assert.match(html, /SGH Inpatient Psychiatry/)
    assert.doesNotMatch(html, /row 37|Capacity in this draft/)
    const alternativeHtml = renderToStaticMarkup(createElement(RequestDetails, {
      ...props, rows: [{ ...row, status: 'met', reason: null, alternatives: [
        { ...row, request: { ...row.request, posting_request: 'Option A' } },
        { ...row, status: 'met', request: { ...row.request, posting_request: 'Option B' } },
      ] }],
    }, 'Details'))
    assert.match(alternativeHtml, /Requested alternatives/)
    assert.match(alternativeHtml, /Option A/)
    assert.match(alternativeHtml, /<small>OR<\/small>/)
    assert.match(alternativeHtml, /Option B/)
    assert.match(alternativeHtml, /Selected/)
    assert.doesNotMatch(alternativeHtml, /Request not met|R4 Inpatient must be outside IMH/)

    for (const [months, expected] of [
      [Array.from({ length: 12 }, (_, i) => `${i < 6 ? 2027 : 2028}-${String((i + 6) % 12 + 1).padStart(2, '0')}`), 'Jul 2027–Jun 2028'],
      [['2027-12', '2028-01', '2028-03'], 'Dec 2027–Jan 2028, Mar 2028'],
      [['2028-04'], 'Apr 2028'],
    ] as const) {
      const assigned = renderToStaticMarkup(createElement(RequestDetails, {
        ...props, rows: [{ ...row, assigned: [{ label: 'Clinic', months: [...months] }] }],
      }, 'Details'))
      assert.ok(assigned.includes(`<small>${expected}</small>`))
    }
    const counts = ['2028-07', '2028-08', '2028-09'].map((month, i) => ({
      month, requirement_id: 'r4.inpatient_psychiatry', residency_year: 'R4', category: 'core',
      institution: 'IMH', label: 'IMH Inpatient Psychiatry', source: { sheet: 'Postings', row: 31 },
      max: 6, assigned: i < 2 ? 6 : 5,
    }))
    const withCapacity = renderToStaticMarkup(createElement(RequestDetails, {
      ...props, rows: [{ ...row, capacity: counts }],
    }, 'Details'))
    assert.match(withCapacity, /<\/dl><details class="request-capacity"><summary>Capacity in this draft<\/summary>/)
    assert.match(withCapacity, /Jul\u2013Aug 2028<\/span><span class="at-max">6 assigned \/ 6 max/)
    assert.match(withCapacity, /Sep 2028<\/span><span>5 assigned \/ 6 max/)
    assert.doesNotMatch(withCapacity, /These counts show the current draft/)
    const { default: CapacityDetails } = await vite.ssrLoadModule('/src/components/CapacityDetails.tsx')
    const capacity = renderToStaticMarkup(createElement(CapacityDetails, { rows: [{
      month: '2027-07', requirement_id: 'r4.forensic', residency_year: 'R4', institution: 'IMH', label: 'IMH Forensic Psychiatry',
      max: 6, assigned: 7, source: { sheet: 'Postings', row: 30 },
      residents: Array.from({ length: 7 }, (_, index) => ({ name: `Assigned ${index + 1}`, source: { sheet: 'Plan', row: index + 2 } })),
    }] }, '7/6'))
    assert.match(capacity, /popover="auto"/)
    assert.match(capacity, /7 assigned \/ 6 max/)
    assert.match(capacity, /All assigned residents, across recorded R-years/)
    for (let index = 1; index <= 7; index++) assert.match(capacity, new RegExp(`Assigned ${index}`))
    assert.match(capacity, /Close details/)
    assert.doesNotMatch(capacity, /row 30/)

  } finally {
    await vite.close()
  }
})

test('swap preview stays on the source row after leaving an ineligible destination', () => {
  const from = resident.source
  const other = { sheet: 'Timetable', row: 4 }
  const affected = [{ source: from, month: '2027-07' }, { source: other, month: '2027-07' }]
  const invalid = { severity: 'hard' as const, code: 'invalid_destination', message: 'Choose a block in the source row.', affected }
  const capacity = { severity: 'soft' as const, code: 'capacity_overflow', message: 'The swap would exceed capacity.', affected }

  assert.deepEqual(draftPreviewIssuesForRow([invalid], other, from, other), [invalid])
  assert.deepEqual(draftPreviewIssuesForRow([invalid], other, from, from), [])
  assert.deepEqual(draftPreviewIssuesForRow([capacity], other, from, from), [])
  assert.deepEqual(draftPreviewIssuesForRow([capacity], from, from, from), [capacity])
  assert.deepEqual(draftPreviewIssuesForRow([capacity], other), [capacity])
})

test('released swaps wait, require confirmation for warnings, and show blocking reasons', async () => {
  const edited: DraftSchedule = { ...draft, status: 'edited' }
  const soft = { severity: 'soft' as const, code: 'capacity', message: 'The swap would exceed capacity.', affected: [] }
  const hard = { severity: 'hard' as const, code: 'timing', message: 'The posting must come first.', affected: [] }
  const warning = { draft: edited, issues: [soft] }
  const blocked = { draft: edited, issues: [soft, hard] }
  assert.equal(draftSwapOutcome({ draft: edited, issues: [] }), 'clean')
  assert.equal(draftSwapOutcome(warning), 'warning')
  assert.equal(draftSwapOutcome(blocked), 'blocked')
  assert.equal(draftSwapOutcome({ draft: null, issues: [] }), 'blocked')

  const vite = await createServer({ server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' })
  try {
    const { DraftMoveFeedback } = await vite.ssrLoadModule('/src/components/DraftBlockEditor.tsx')
    const props = { anchor: {} as HTMLElement, kind: 'swap', onApply: () => {}, onDismiss: () => {} }
    const checking = renderToStaticMarkup(createElement(DraftMoveFeedback, { ...props, checking: true, preview: null }))
    assert.match(checking, /Checking the swap.*Cancel/)
    assert.doesNotMatch(checking, /Apply swap/)
    const confirmation = renderToStaticMarkup(createElement(DraftMoveFeedback, { ...props, checking: false, preview: warning,
      proposal: 'Jul 2027, Geriatric Psychiatry. Oct 2027, Addiction Medicine.' }))
    assert.match(confirmation, /role="dialog".*aria-describedby=.*exceed capacity.*Cancel.*Apply swap/)
    assert.match(confirmation, /Proposed arrangement\. Jul 2027, Geriatric Psychiatry\. Oct 2027, Addiction Medicine\./)
    assert.match(confirmation, /<p[^>]*>The swap would exceed capacity\.<\/p>/)
    const ratio = (month: string, medicine: number, neurology: number) => ({ ...soft,
      code: 'monthly_medicine_neurology_ratio',
      message: `In ${month}, the SGH route would have ${medicine} in Medicine and ${neurology} in Neurology. The usual split is 2 to 1.` })
    const issues = [
      { ...soft, code: 'capacity_overflow', message: 'September to October at SGH would have 8 residents in General Medicine. The max is 6.' },
      { ...soft, code: 'capacity_overflow', message: 'November to December at SGH would have 4 residents in Neurology. The max is 3.' },
      ratio('September', 8, 3), ratio('October', 8, 3), ratio('December', 6, 4),
    ]
    const summary = renderToStaticMarkup(createElement(DraftMoveFeedback, { ...props, checking: false, preview: { draft: edited, issues } }))
    assert.equal(summary.match(/<li\b/g)?.length, 3)
    assert.match(summary, /<strong>Capacity exceeded: <\/strong>SGH General Medicine has 8 residents in Sep and Oct \(max 6\)\./)
    assert.match(summary, /SGH Neurology has 4 residents in Nov and Dec \(max 3\)/)
    assert.match(summary, /<strong>R1 ratio off target: <\/strong>SGH has 8 Medicine to 3 Neurology in Sep and Oct and 6 to 4 in Dec\. The usual split is 2 to 1\./)
    const rejection = renderToStaticMarkup(createElement(DraftMoveFeedback, { ...props, checking: false, preview: blocked }))
    assert.match(rejection, /Swap blocked.*posting must come first.*Dismiss/)
    assert.match(rejection, /<ul[^>]*><li[^>]*>The swap would exceed capacity\.<\/li><li[^>]*>The posting must come first\.<\/li><\/ul>/)
    assert.doesNotMatch(rejection, /Apply swap/)
    const insertion = renderToStaticMarkup(createElement(DraftMoveFeedback, { ...props, kind: 'insert', checking: false, preview: warning }))
    assert.match(insertion, /Review move warning.*Cancel.*Apply move/)
  } finally {
    await vite.close()
  }
})

test('swap previews exchange both posting labels across fixed leave without moving other blocks', () => {
  const first = '2027-07', second = '2027-11', third = '2028-02'
  const blocks = [first, first, undefined, first, second, second, second, third, undefined]
  const dates = ['2027-07', '2027-08', '2027-09', '2027-10', '2027-11', '2027-12', '2028-01', '2028-02', '2028-03']
  const months: DraftSchedule['residents'][number]['months'] = blocks.map((block_start, index) => ({
    month: dates[index], status: block_start ? 'posting' : index === 2 ? 'loa' : 'outside_draft_scope',
    label: block_start ? 'Posting' : null, block_start,
  }))
  assert.deepEqual(draftSwapLayout(months, first, second), [second, second, undefined, second, first, first, first, third, undefined])
  assert.equal(draftSwapLayout(months, first, third), null)
  assert.deepEqual(months.map((month) => month.block_start), blocks)
})

test('insertion previews reflow unequal blocks around fixed leave and identify adjacent no-ops', () => {
  const first = '2027-07', second = '2027-11', third = '2027-12'
  const blocks = [first, first, undefined, first, second, third, third]
  const months: DraftSchedule['residents'][number]['months'] = blocks.map((block_start, index) => ({
    month: index === 6 ? '2028-01' : `2027-${String(7 + index).padStart(2, '0')}`, status: block_start ? 'posting' : 'loa',
    label: block_start ? 'Same posting label' : null, block_start,
  }))
  assert.deepEqual(draftInsertion(months, third, first, 'before'), {
    changed: true, blocks: [third, third, undefined, first, first, first, second],
  })
  assert.deepEqual(draftInsertion(months, first, third, 'after'), {
    changed: true, blocks: [second, third, undefined, third, first, first, first],
  })
  assert.deepEqual(draftInsertion(months, first, second, 'before'), { changed: false, blocks })
  months[2].status = 'outside_draft_scope'
  assert.equal(draftInsertion(months, third, first, 'before'), null)
})

test('drag narrows the adjacent no-op edge for equal training lengths, including across leave', () => {
  const dates = ['2027-07', '2027-08', '2027-09', '2027-10', '2027-11', '2027-12', '2028-01', '2028-02', '2028-03']
  const july = dates[0], november = dates[4], january = dates[6], march = dates[8]
  const starts = [july, undefined, july, undefined, november, november, january, january, march]
  const months: DraftSchedule['residents'][number]['months'] = dates.map((month, index) => ({
    month, status: starts[index] ? 'posting' : 'loa', block_start: starts[index], label: starts[index] ? 'Posting' : null,
  }))
  assert.deepEqual(draftDropEdges(months, july, november), [0.1, 0.3])
  assert.deepEqual(draftDropEdges(months, november, july), [0.3, 0.1])
  assert.deepEqual(draftDropEdges(months, november, january), [0.1, 0.3])
  assert.deepEqual(draftDropEdges(months, july, january), [0.3, 0.3])
  assert.deepEqual(draftDropEdges(months, january, march), [0.3, 0.3])
  assert.deepEqual(draftDropEdges(months, july, july), [0.3, 0.3])
  months[3].status = 'outside_draft_scope'
  assert.deepEqual(draftDropEdges(months, july, november), [0.3, 0.3])
})

test('request totals count distinct requests across the draft while filters combine with resident search', () => {
  const request = { posting_request: 'Example', period: null, source: { sheet: 'Request', row: 2 } }
  const other = { ...resident, name: 'Other', source: { sheet: 'Planning', row: 20 } }
  const skipped = { ...resident, name: 'Skipped', source: { sheet: 'Planning', row: 21 } }
  const data: DraftSchedule = { ...draft, residents: [
    { ...draft.residents[0], source: resident.source, requests: [
      { request, status: 'met' }, { request, status: 'met' }, { request, status: 'not_met' },
      { request, status: 'not_met', duplicate_of: 2 },
    ] },
    { ...draft.residents[0], source: other.source, requests: [{ request, status: 'pending' }] },
  ] }
  const people = [resident, other, skipped]
  assert.deepEqual(requestTotals(data), { met: 2, not_met: 1, pending: 1 })
  for (const status of ['met', 'not_met', 'pending'] as const) {
    assert.deepEqual(filterRequestResidents(people, data, status), [status === 'pending' ? other : resident])
  }
  assert.equal(filterRequestResidents(people, data, null), people)
  assert.deepEqual(filterRequestResidents([other], data, 'not_met'), []) // Name search applied first.
  assert.deepEqual(requestTotals(data), { met: 2, not_met: 1, pending: 1 }) // Search never changes totals.
  assert.equal(filterRequestResidents(people, null, 'not_met'), people)
  assert.deepEqual(requestTotals(null), { met: 0, not_met: 0, pending: 0 })
  assert.deepEqual(requestTotals({ ...data, status: 'blocked' }), { met: 0, not_met: 0, pending: 0 })
})


test('capacity review groups exact postings and only merges consecutive months with matching counts', () => {
  const base = { requirement_id: 'r4.emergency', residency_year: 'R4', category: 'core' as const, institution: 'IMH', label: 'IMH Emergency Psychiatry', source: { sheet: 'Postings', row: 31 }, max: 6, assigned: 7, residents: [] }
  const rows = [
    { ...base, month: '2028-01' }, { ...base, month: '2027-12' },
    { ...base, month: '2028-02', assigned: 8 }, { ...base, month: '2028-04', assigned: 8 },
    { ...base, month: '2028-01', requirement_id: 'r5.emergency', residency_year: 'R5' },
  ]
  const groups = groupedCapacityRows(rows)
  assert.equal(groups.length, 2)
  assert.deepEqual(groups[0].periods, [
    { start: '2027-12', end: '2028-01', assigned: 7, max: 6 },
    { start: '2028-02', end: '2028-02', assigned: 8, max: 6 },
    { start: '2028-04', end: '2028-04', assigned: 8, max: 6 },
  ])
  assert.equal(rows[0].month, '2028-01')
})

test('failed regeneration leaves the saved draft and its timing available until a successful replacement', () => {
  const original: SavedDraft = { year: 2027, elapsedSeconds: 121, reviewSignature: '[]', data: {
    status: 'feasible', cutoff: '2027-06', residents: [], blockers: [],
    optimisation_stages: [{ priority: 'initial_feasibility', status: 'feasible', wall_time_seconds: 4 }],
  } }
  const state = { saved: original, failure: null }
  const active = { cancelled: false, invalidated: false }
  const blockers = [{ code: 'unresolved_history', source: { sheet: 'Annual timetable', row: 12 } }]

  for (const status of ['blocked', 'infeasible', 'unknown', 'model_invalid'] as const) {
    const failed = { ...original, elapsedSeconds: 5, data: { ...original.data, status, blockers } }
    const afterFailure = settleDraftAttempt(state, failed, active)
    assert.equal(afterFailure.saved, original)
    assert.deepEqual(afterFailure.failure?.blockers, blockers)
    assert.equal(afterFailure.failure?.status, status)
    for (const replacementStatus of ['feasible', 'optimal'] as const) {
      const replacement = { ...original, elapsedSeconds: 269, data: { ...original.data, status: replacementStatus } }
      assert.deepEqual(settleDraftAttempt(afterFailure, replacement, active), { saved: replacement, failure: null })
    }
  }
})

test('a late successful solve cannot replace a retained draft after cancel or restore an invalidated draft', () => {
  const original: SavedDraft = { year: 2027, elapsedSeconds: 120, reviewSignature: '[]', data: {
    status: 'feasible', cutoff: '2027-06', residents: [], blockers: [],
  } }
  const replacement = { ...original, elapsedSeconds: 250, data: { ...original.data, status: 'optimal' as const } }
  const retained = { saved: original, failure: null }
  const discarded = { saved: null, failure: null }
  assert.equal(settleDraftAttempt(retained, replacement, { cancelled: true, invalidated: false }), retained)
  assert.equal(settleDraftAttempt(discarded, replacement, { cancelled: false, invalidated: true }), discarded)
})
