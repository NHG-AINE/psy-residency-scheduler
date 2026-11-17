import assert from 'node:assert/strict'
import test from 'node:test'
import { parseSession, sessionWriter } from '../src/lib/workbook-session.ts'
import type { WorkbookSession } from '../src/lib/workbook-session.ts'
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

test('review signatures ignore equivalent ordering but change with actual decisions', () => {
  const first = { kind: 'alias', context: { label: 'Old label', recorded_year: 'R2', category: 'core' },
    target: { key: 'target', signature: 'catalogue' } } as const
  const second = { ...first, context: { ...first.context, label: 'Another label' } }
  const store = { version: 1, decisions: [first, second] } as ReviewStore
  assert.equal(reviewSignature(store), reviewSignature({ ...store, decisions: [second, first] }))
  assert.notEqual(reviewSignature(store), reviewSignature({ ...store, decisions: [first] }))
  assert.notEqual(reviewSignature(store), reviewSignature({ ...store, decisions: [{ ...first, target: { ...first.target, signature: 'changed' } }, second] }))
})
