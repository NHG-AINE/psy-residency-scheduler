import assert from 'node:assert/strict'
import test from 'node:test'
import { draftBlockerLabel, draftPostings, generateDraft, updatedResidentCount } from '../src/lib/draft-schedule.ts'
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
    months: resident.postings.map((posting, index) => ({ month: posting.month, status: index === 2 ? 'outside_r1_scope' : 'posting', label: 'IMH Inpatient Psychiatry' })) }],
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
    assert.equal(url, '/api/draft-r1')
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
