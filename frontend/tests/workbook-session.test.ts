import assert from 'node:assert/strict'
import test from 'node:test'
import { draftUndoPreview, prepareDraftEdit, undoDraftEdit } from '../src/lib/draft-edit-history.ts'
import { parseSession, sessionWriter } from '../src/lib/workbook-session.ts'
import type { WorkbookSession } from '../src/lib/workbook-session.ts'
import type { DraftChange, DraftSchedule } from '../src/lib/draft-schedule.ts'
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
  const { saved, planned } = draftHistoryFixture()
  const original = saved.draft!.data
  saved.draft = { ...saved.draft!, undo: [original], data: { ...planned([2, 1, 3, 4]), edit_warnings: [
    { severity: 'soft', code: 'posting_balance', message: 'Monthly posting distribution is less even.', affected: [] },
  ] } }
  const restored = parseSession(structuredClone(saved))
  assert.deepEqual(restored?.draft, saved.draft)
  assert.equal(restored?.draft?.undo?.at(-1)?.status, 'feasible')
})

const [july, august, september, october] = ['2027-07', '2027-08', '2027-09', '2027-10']
const resident = { sheet: 'Latest', row: 2 }
const swapA = { kind: 'swap', resident, start: july, destination: august } as const
const swapB = { kind: 'swap', resident, start: september, destination: october } as const
const reverseA = { ...swapA, start: august, destination: july }
const edgeA = { ...swapA, kind: 'insert', side: 'after' } as const
const reverseEdgeA = { ...reverseA, kind: 'insert', side: 'after' } as const
const withoutReplay = () => { throw new Error('Unexpected replay') }
const postingEdit = (start: string, option: number) => ({
  kind: 'edit', resident, start, posting: 'Posting', institution: 'Site', offering: { sheet: 'Postings', row: 2, column: String(option) },
}) as const

function draftHistoryFixture(other?: { sheet: string; row: number }) {
  const saved = session()
  const original = saved.draft!.data
  const row = (source: typeof resident, order: number[]): DraftSchedule['residents'][number] => ({
    source, name: null, mcr: null, carryforward: [],
      months: [july, august, september, october].map((month, i) => ({ month, block_start: month, status: 'posting', label: 'Posting',
        target: { category: 'core', source: { sheet: 'Postings', row: 2, column: String(order[i]) } } })),
  })
  const planned = (order: number[], status: DraftSchedule['status'] = 'edited', otherOrder = [1, 2, 3, 4]): DraftSchedule => ({
    ...original, status, residents: [row(resident, order), ...(other ? [row(other, otherOrder)] : [])],
    edit_options: Array.from({ length: 6 }, (_, index) => ({
      posting: 'Posting', institution: 'Site', category: 'core', residency_year: 'R2', label: 'Posting',
      requirement_id: 'r2.geriatric_psychiatry', source: postingEdit(july, index + 1).offering,
    })),
  })
  saved.draft!.data = planned([1, 2, 3, 4], 'feasible')
  return { saved, planned }
}

test('undo previews a reopened swap with identical labels and preserves the preceding history', async () => {
  const { saved, planned } = draftHistoryFixture()
  const first = await prepareDraftEdit(saved.draft!, swapA, planned([2, 1, 3, 4]), withoutReplay)
  saved.draft = await prepareDraftEdit(first, swapB, planned([2, 1, 4, 3]), withoutReplay)
  const reopened = parseSession(structuredClone(saved))!.draft!
  const restored = undoDraftEdit(reopened)!
  for (const current of [reopened, { ...reopened, undoChanges: undefined }]) {
    const preview = draftUndoPreview(current, restored.data)
    assert.deepEqual(preview?.positions, [july, august, october, september])
    assert.deepEqual(preview?.months, [september, october])
  }
  assert.deepEqual(restored, first)
})

test('undo previews every block affected by insertion around leave, including identical adjacent postings', () => {
  const { saved, planned } = draftHistoryFixture()
  const november = '2027-11', december = '2027-12', january = '2028-01'
  const dates = [july, august, september, october, november, december, january]
  const plan = (starts: (string | undefined)[], status: DraftSchedule['status']) => {
    const draft = planned([1, 2, 3, 4], status)
    draft.residents[0].months = dates.map((month, index) => ({
      month, block_start: starts[index], status: starts[index] ? 'posting' : 'loa', label: starts[index] ? 'Inpatient' : null,
    }))
    return draft
  }
  const original = plan([july, july, undefined, october, november, november, november], 'feasible')
  const edited = plan([july, august, undefined, august, august, december, december], 'edited')
  saved.draft = { ...saved.draft!, undo: [original], data: edited,
    undoChanges: [{ kind: 'insert', resident, start: july, destination: november, side: 'after' }] }
  const reverted = undoDraftEdit(saved.draft)!
  for (const current of [saved.draft, { ...saved.draft, undoChanges: undefined }]) {
    const preview = draftUndoPreview(current, reverted.data)
    assert.deepEqual(preview?.positions, [december, december, undefined, july, august, august, august])
    assert.deepEqual(preview?.months, dates.filter((month) => month !== september))
  }
  assert.equal(reverted.data, original)
})

test('undo previews a label change in place in current and legacy edit history', () => {
  const { saved, planned } = draftHistoryFixture()
  const original = saved.draft!.data
  const edited = planned([1, 5, 3, 4])
  edited.residents[0].months[1].label = 'New label'
  const current = { ...saved.draft!, undo: [original], data: edited }
  const change: DraftChange = { kind: 'edit', resident, start: august, posting: 'New label', institution: 'IMH', offering: { sheet: 'Postings', row: 5 } }
  for (const history of [current, { ...current, undoChanges: [change] }]) {
    const preview = draftUndoPreview(history, original)
    assert.equal(preview?.positions, null)
    assert.deepEqual(preview?.months, [august])
    assert.equal(preview?.restored[1].label, 'Posting')
  }
})

test('cancels a reversed swap across a saved session and rebuilds undo for an independent later swap', async () => {
  const { saved, planned } = draftHistoryFixture()
  const generated = saved.draft!
  const afterA = await prepareDraftEdit(generated, swapA, planned([2, 1, 3, 4]), withoutReplay)
  const afterAB = await prepareDraftEdit(afterA, swapB, planned([2, 1, 4, 3]), withoutReplay)
  const restored = parseSession(structuredClone({ ...saved, draft: afterAB }))!.draft!
  const afterB = { ...planned([1, 2, 4, 3]), soft_results: { distribution_deviation: 37, ratio_deviation: 12 } }
  let replayed = 0
  const reversed = await prepareDraftEdit(restored, reverseA, planned([1, 2, 4, 3]), async (base, change) => {
    replayed++
    assert.deepEqual(base, generated.data)
    assert.deepEqual(change, swapB)
    return { draft: afterB, issues: [] }
  })
  assert.equal(replayed, 1)
  assert.equal(reversed.data, afterB)
  assert.deepEqual(reversed.undoChanges, [swapB])
  assert.deepEqual(restored, afterAB)
  const reopened = parseSession(structuredClone({ ...saved, draft: reversed }))!.draft!
  const undone = undoDraftEdit(reopened)!
  assert.deepEqual(undone.data, generated.data)
  assert.equal(undoDraftEdit(undone), null)
})

test('preserves a later swap of the same months on a different resident row', async () => {
  const other = { ...resident, row: 3 }
  const { saved, planned } = draftHistoryFixture(other)
  const generated = saved.draft!
  const changeB = { ...swapA, resident: other }
  const afterA = await prepareDraftEdit(generated, swapA, planned([2, 1, 3, 4]), withoutReplay)
  const afterAB = await prepareDraftEdit(afterA, changeB, planned([2, 1, 3, 4], 'edited', [2, 1, 3, 4]), withoutReplay)
  const afterB = planned([1, 2, 3, 4], 'edited', [2, 1, 3, 4])
  const result = await prepareDraftEdit(afterAB, reverseA, afterB, async (base, change) => {
    assert.equal(base, generated.data)
    assert.deepEqual(change, changeB)
    return { draft: afterB, issues: [] }
  })
  assert.deepEqual(result.undoChanges, [changeB])
  assert.equal(result.data, afterB)
  const undone = undoDraftEdit(result)!
  assert.equal(undone.data, generated.data)
  assert.equal(undoDraftEdit(undone), null)
})

test('repeatedly reversing the latest swap restores the generated draft and clears undo', async () => {
  const { saved, planned } = draftHistoryFixture()
  const generated = saved.draft!.data
  for (let repeat = 0; repeat < 3; repeat++) {
    saved.draft = await prepareDraftEdit(saved.draft!, swapA, planned([2, 1, 3, 4]), withoutReplay)
    saved.draft = await prepareDraftEdit(saved.draft, reverseA, planned([1, 2, 3, 4]), withoutReplay)
    assert.equal(saved.draft.data, generated)
    assert.equal(undoDraftEdit(saved.draft), null)
  }
})

test('reversing a posting edit restores the generated draft live and after reopening an older session', async () => {
  const { saved, planned } = draftHistoryFixture()
  const generated = saved.draft!
  const edited = await prepareDraftEdit(generated, postingEdit(july, 5), planned([5, 2, 3, 4]), withoutReplay)
  const reverse = postingEdit(july, 1)
  const restored = await prepareDraftEdit(edited, reverse, planned([1, 2, 3, 4]), withoutReplay)
  assert.equal(restored.data, generated.data)
  assert.equal(undoDraftEdit(restored), null)

  const old = { ...edited, data: planned([1, 2, 3, 4]), undo: [generated.data, edited.data],
    undoChanges: [...edited.undoChanges!, reverse] }
  const reopened = parseSession(structuredClone({ ...saved, draft: old }))!.draft!
  assert.deepEqual(reopened.data, generated.data)
  assert.equal(undoDraftEdit(reopened), null)
})

test('reversing a posting edit keeps an independent intervening edit undoable after reopening', async () => {
  const { saved, planned } = draftHistoryFixture()
  const generated = saved.draft!
  const editB = postingEdit(september, 6)
  const afterA = await prepareDraftEdit(generated, postingEdit(july, 5), planned([5, 2, 3, 4]), withoutReplay)
  const afterAB = await prepareDraftEdit(afterA, editB, planned([5, 2, 6, 4]), withoutReplay)
  const afterB = planned([1, 2, 6, 4])
  let replayed = 0
  for (const current of [afterAB, { ...afterAB, undoChanges: undefined }]) {
    const reversed = await prepareDraftEdit(current, postingEdit(july, 1), afterB, async (base, change) => {
      replayed++
      assert.equal(base, generated.data)
      assert.deepEqual(change, editB)
      return { draft: afterB, issues: [] }
    })
    const reopened = parseSession(structuredClone({ ...saved, draft: reversed }))!.draft!
    assert.deepEqual(reopened.data, afterB)
    assert.deepEqual(reopened.undoChanges, [editB])
    const undone = undoDraftEdit(reopened)!
    assert.deepEqual(undone.data, generated.data)
    assert.equal(undoDraftEdit(undone), null)
  }
  assert.equal(replayed, 2)
})

test('reversing the latest edit to the same block keeps the earlier edit undoable', async () => {
  const { saved, planned } = draftHistoryFixture()
  const first = postingEdit(july, 5), second = postingEdit(july, 6), reverse = postingEdit(july, 5)
  const afterFirst = await prepareDraftEdit(saved.draft!, first, planned([5, 2, 3, 4]), withoutReplay)
  const afterSecond = await prepareDraftEdit(afterFirst, second, planned([6, 2, 3, 4]), withoutReplay)
  const returned = planned([5, 2, 3, 4])
  assert.deepEqual(await prepareDraftEdit(afterSecond, reverse, returned, withoutReplay), afterFirst)

  const old = { ...afterSecond, data: returned, undo: [...afterSecond.undo!, afterSecond.data],
    undoChanges: [...afterSecond.undoChanges!, reverse] }
  for (const draft of [old, { ...old, undoChanges: undefined }]) {
    const reopened = parseSession(structuredClone({ ...saved, draft }))!.draft!
    assert.deepEqual(reopened, afterFirst)
  }
})

test('keeps chronological undo when an intervening swap moves the edited posting', async () => {
  const { saved, planned } = draftHistoryFixture()
  const edited = await prepareDraftEdit(saved.draft!, postingEdit(july, 5), planned([5, 2, 3, 4]), withoutReplay)
  const swapped = await prepareDraftEdit(edited, swapA, planned([2, 5, 3, 4]), withoutReplay)
  let replayed = false
  const changed = await prepareDraftEdit(swapped, postingEdit(july, 1), planned([1, 5, 3, 4]), async () => {
    replayed = true
    return { draft: null, issues: [] }
  })
  assert.equal(replayed, false)
  assert.deepEqual(undoDraftEdit(parseSession(structuredClone({ ...saved, draft: changed }))!.draft!), swapped)
})

test('restores a legacy session already at the generated plan, including original diagnostics', () => {
  const { saved, planned } = draftHistoryFixture()
  const generated = saved.draft!
  const afterA = planned([2, 1, 3, 4])
  const restoredPlacement = planned([1, 2, 3, 4])
  restoredPlacement.optimisation_stages = undefined
  const record = { ...generated, data: restoredPlacement, undo: [generated.data, afterA] }
  const reopened = parseSession(structuredClone({ ...saved, draft: record }))!.draft!
  assert.deepEqual(reopened.data, generated.data)
  assert.equal(undoDraftEdit(reopened), null)

  const originalRow = restoredPlacement.residents[0]
  for (const difference of [
    { carryforward: [{ institution: 'IMH', months: 2, requirement_id: 'r1.inpatient' }] },
    { route: 'different route' },
  ]) {
    restoredPlacement.residents[0] = { ...originalRow, ...difference }
    const changedPlan = parseSession(structuredClone({ ...saved, draft: record }))!.draft!
    assert.deepEqual(changedPlan.data, restoredPlacement)
    assert.ok(undoDraftEdit(changedPlan))
  }
})

test('cancels an edge reorder and preserves an independent later change for new and legacy sessions', async () => {
  const { saved, planned } = draftHistoryFixture()
  const generated = saved.draft!
  const afterA = await prepareDraftEdit(generated, edgeA, planned([2, 1, 3, 4]), withoutReplay)
  const afterAB = await prepareDraftEdit(afterA, swapB, planned([2, 1, 4, 3]), withoutReplay)
  for (const draft of [afterAB, { ...afterAB, undoChanges: undefined }]) {
    const reopened = parseSession(structuredClone({ ...saved, draft }))!.draft!
    const afterB = planned([1, 2, 4, 3])
    const restored = await prepareDraftEdit(reopened, reverseEdgeA, afterB, async (base, action) => {
      assert.deepEqual(base, generated.data)
      assert.deepEqual(action, swapB)
      return { draft: afterB, issues: [] }
    })
    assert.deepEqual(restored.undoChanges, [swapB])
    assert.deepEqual(undoDraftEdit(restored)?.data, generated.data)
  }
})

test('returns to the generated draft after reversing an unequal insertion, including legacy snapshots', async () => {
  const { saved, planned } = draftHistoryFixture()
  const generated = saved.draft!
  generated.data.residents[0].months[1] = { ...generated.data.residents[0].months[0], month: august }
  const moved = planned([3, 1, 1, 4])
  moved.residents[0].months[2].block_start = august
  const restored = await prepareDraftEdit({ ...generated, data: moved, undo: [generated.data] },
    edgeA, { ...generated.data, status: 'edited' }, withoutReplay)
  assert.equal(restored.data, generated.data)
  assert.equal(undoDraftEdit(restored), null)
})

test('keeps chronological undo after a later change touches either swap block', async () => {
  const { saved, planned } = draftHistoryFixture()
  const afterA = await prepareDraftEdit(saved.draft!, swapA, planned([2, 1, 3, 4]), withoutReplay)
  const edit = { kind: 'edit', start: july, resident, posting: 'Posting', institution: 'Site', offering: { sheet: 'Postings', row: 2 } } as const
  const insert = { kind: 'insert', start: july, destination: october, side: 'after', resident } as const
  for (const [change, next, reversed] of [[edit, [5, 1, 3, 4], [1, 5, 3, 4]], [insert, [1, 3, 4, 2], [3, 1, 4, 2]]] as const) {
    const modified = await prepareDraftEdit(afterA, change, planned([...next]), withoutReplay)
    let replayed = false
    const result = await prepareDraftEdit(modified, reverseA, planned([...reversed]), async () => {
      replayed = true
      return { draft: null, issues: [] }
    })
    assert.equal(replayed, false)
    assert.deepEqual(undoDraftEdit(result), modified)
  }
})

test('falls back to chronological undo if replay fails or alters a block boundary', async () => {
  const { saved, planned } = draftHistoryFixture()
  const afterA = await prepareDraftEdit(saved.draft!, swapA, planned([2, 1, 3, 4]), withoutReplay)
  const afterAB = await prepareDraftEdit(afterA, swapB, planned([2, 1, 4, 3]), withoutReplay)
  const reversed = planned([1, 2, 4, 3])
  const differentBoundary = structuredClone(reversed)
  differentBoundary.residents[0].months[3].block_start = september
  for (const badDraft of [null, differentBoundary]) {
    const result = await prepareDraftEdit(afterAB, reverseA, reversed, async (_, change: DraftChange) => {
      assert.deepEqual(change, swapB)
      return { draft: badDraft, issues: [] }
    })
    assert.equal(result.data, reversed)
    assert.deepEqual(undoDraftEdit(result), afterAB)
  }
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
