import assert from 'node:assert/strict'
import test from 'node:test'
import { parseSession, sessionWriter } from '../src/lib/workbook-session.ts'
import type { WorkbookSession } from '../src/lib/workbook-session.ts'
import type { DraftSchedule } from '../src/lib/draft-schedule.ts'
import { reviewSignature } from '../src/lib/history-review.ts'
import type { ReviewStore } from '../src/lib/history-review.ts'

function session(): WorkbookSession {
  return { version: 1, file: new File(['workbook bytes'], 'test.xlsx', { lastModified: 123 }), fileName: 'test.xlsx', lastModified: 123,
    workbook: { target_year: 2026, available_years: [{ year: 2026, sheet: 'Old' }, { year: 2027, sheet: 'Latest' }], target_sheet: 'Old',
      months: [], residents: [], histories: [], requests: [], warnings: [], postings: { core: [], rows: [] } },
    draft: { year: 2027, elapsedSeconds: 121, reviewSignature: '[]', data: {
      status: 'feasible', cutoff: '2027-06', residents: [], blockers: [],
      optimisation_stages: [{ priority: 'initial_feasibility', status: 'feasible', wall_time_seconds: .25 }],
    } } }
}

test('restores original file bytes, successful historical year and hidden completed latest draft/timing', async () => {
  const saved = session()
  const restored = parseSession({ ...saved, file: new Blob([await saved.file.arrayBuffer()]) })!
  assert.equal(restored.file.name, 'test.xlsx')
  assert.equal(restored.file.lastModified, 123)
  assert.equal(await restored.file.text(), 'workbook bytes')
  assert.equal(restored.workbook.target_year, 2026)
  assert.deepEqual(restored.draft, saved.draft)
  assert.equal(parseSession(undefined), null)
  for (const value of [{ ...saved, version: 2 }, { ...saved, workbook: null },
    { ...saved, draft: { ...saved.draft, year: 2026 } }, { ...saved, draft: { ...saved.draft, data: { status: 'unknown' } } }]) {
    assert.throws(() => parseSession(value), /saved|Saved/)
  }
})

test('queued saves cannot resurrect a removed session and in-flight saves precede draft discard', async () => {
  let stored: WorkbookSession | null = null
  let release!: () => void
  const gate = new Promise<void>((resolve) => { release = resolve })
  const writer = sessionWriter(async (value) => { if (value?.draft) await gate; stored = value })
  const stale = writer(session())
  const remove = writer(null)
  release()
  await Promise.all([stale, remove])
  assert.equal(stored, null)
  let start!: () => void
  const started = new Promise<void>((resolve) => { start = resolve })
  let finish!: () => void
  const pending = new Promise<void>((resolve) => { finish = resolve })
  const inFlight = sessionWriter(async (value) => { if (value?.draft) { start(); await pending } stored = value })
  const completed = inFlight(session())
  await started
  const discarded = inFlight({ ...session(), draft: null })
  finish()
  await Promise.all([completed, discarded])
  assert.equal((stored as WorkbookSession | null)?.draft, null)
  let fail = true
  const recovery = sessionWriter(async (value) => { if (fail) throw new Error('storage disabled'); stored = value })
  await assert.rejects(recovery(session()), /disabled/)
  fail = false
  await recovery(null)
  assert.equal(stored, null)
})

test('restores edited draft warnings and original undo snapshot alongside workbook bytes', () => {
  const saved = session()
  const original = saved.draft!.data
  saved.draft = { ...saved.draft!, undo: [original], data: { ...original, status: 'edited', edit_warnings: [
    { severity: 'soft', code: 'posting_balance', message: 'Monthly posting distribution is less even.', affected: [] },
  ] } }
  const restored = parseSession(structuredClone(saved))
  assert.deepEqual(restored?.draft, saved.draft)
  assert.equal(restored?.draft?.undo?.at(-1)?.status, 'feasible')
})

test('recovers R1 Medicine boundaries from undo history after a saved swap and later edit', () => {
  const saved = session()
  const [july, aug, sep, oct, nov, dec, jan] = ['2026-07', '2026-08', '2026-09', '2026-10', '2026-11', '2026-12', '2027-01']
  type DraftMonth = DraftSchedule['residents'][number]['months'][number]
  const medical = (month: string, block_start: string, neurology = false): DraftMonth => ({
    month, block_start, status: 'posting', label: neurology ? 'SGH Neurology' : 'SGH General Medicine',
    target: { category: 'core', requirement_id: neurology ? 'r1.neurology' : 'r1.general_medicine' },
  })
  const leave: DraftMonth = { month: oct, status: 'loa', label: null }
  const split = { source: { sheet: 'Latest', row: 2 }, name: 'Split Medicine', mcr: null, carryforward: [],
    months: [medical(july, july), medical(aug, july), medical(sep, sep, true), leave,
      medical(nov, sep, true), medical(dec, dec), medical(jan, dec)] }
  const merged = [medical(july, july, true), medical(aug, july, true), medical(sep, sep), leave,
    medical(nov, sep), medical(dec, sep), medical(jan, sep)]
  const continuous = { ...split, source: { sheet: 'Latest', row: 3 }, months: merged }
  const original = { ...saved.draft!.data, residents: [split, continuous] }
  const swapped = { ...original, status: 'edited' as const, residents: [{ ...split, months: merged }, continuous] }
  const later = { ...swapped, residents: [swapped.residents[0], { ...continuous, name: 'Other resident' }] }
  saved.draft = { ...saved.draft!, undo: [original, swapped], data: later }

  const restored = parseSession(structuredClone(saved))!.draft!
  const repaired = [july, july, sep, undefined, sep, dec, dec]
  assert.deepEqual(restored.data.residents[0].months.map((month) => month.block_start), repaired)
  assert.deepEqual(restored.undo?.[1].residents[0].months.map((month) => month.block_start), repaired)
  assert.deepEqual(restored.data.residents[1], later.residents[1])
  assert.deepEqual(restored.undo?.[0], original)
  assert.deepEqual(parseSession(structuredClone({ ...saved, draft: restored }))?.draft, restored)
  assert.deepEqual(parseSession({ ...saved, draft: { ...saved.draft, undo: [] } })?.draft?.data, later)
  const malformed = { ...swapped, residents: [null, { ...split, months: [null] }] }
  assert.deepEqual(parseSession({ ...saved, draft: { ...saved.draft, undo: [original, malformed] } })?.draft?.data, later)
})

test('review signatures ignore equivalent ordering but change with actual decisions', () => {
  const first = { kind: 'alias', context: { label: 'Old label', recorded_year: 'R2', category: 'core' },
    target: { key: 'target', signature: 'catalogue' } } as const
  const second = { ...first, context: { ...first.context, label: 'Another label' } }
  const store = { version: 1, decisions: [first, second] } as ReviewStore
  assert.equal(reviewSignature(store), reviewSignature({ ...store, decisions: [second, first] }))
  assert.notEqual(reviewSignature(store), reviewSignature({ ...store, decisions: [first] }))
  assert.notEqual(reviewSignature(store), reviewSignature({ ...store, decisions: [{ ...first, target: { ...first.target, signature: 'changed' } }, second] }))
})
