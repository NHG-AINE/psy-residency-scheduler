import assert from 'node:assert/strict'
import test from 'node:test'
import { decisionKey, emptyStore, evaluateHistory, historyStatusLabel, matchesHistoryFilter, mergeReviewStores, parseReviewStore, readReviewStore, STORAGE_KEY, writeReviewStore } from '../src/lib/history-review.ts'
import type { ReviewDecision, ReviewStore, HistoryEntry } from '../src/lib/history-review.ts'
import type { Workbook } from '../src/lib/workbook.ts'

const decision = (): ReviewDecision => ({ kind: 'resident', context: { mcr: 'M001', name: 'example resident', recorded_year: 'r3', months: [{ month: '2026-07', value: 'Original label (Remediation)' }, { month: '2026-08', value: 'Original label (Remediation)' }] }, target: { key: '["elective","r2","site department"]', signature: 'reference-content' }, requirement_year: 'R2' })
const store = (): ReviewStore => ({ version: 1, decisions: [decision()] })
function storage() {
  const values = new Map<string, string>()
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) } }
}

test('saved review data survives a new read and JSON export/import without rewriting original values', () => {
  const browser = storage()
  const original = store()
  writeReviewStore(browser, original)
  const restored = readReviewStore(browser)
  assert.equal(restored.error, '')
  assert.deepEqual(restored.store, original)
  assert.deepEqual(parseReviewStore(JSON.stringify(restored.store)), original)
  assert.deepEqual(mergeReviewStores(emptyStore(), restored.store), original)
  assert.match(JSON.stringify(restored.store), /Original label \(Remediation\)/)
  assert.equal(restored.store.decisions[0].context.recorded_year, 'r3')
})

test('resident decision keys survive MCR case, whitespace and month reordering but include dates and original labels', () => {
  const initial = decision()
  if (initial.kind !== 'resident') return
  const reordered = structuredClone(initial)
  reordered.context.mcr = ' m001 '
  reordered.context.months.reverse()
  assert.equal(decisionKey(initial), decisionKey(reordered))
  reordered.context.months[0].value = 'Changed label'
  assert.notEqual(decisionKey(initial), decisionKey(reordered))
  reordered.context.months[0].value = initial.context.months[0].value
  reordered.context.months[0].month = '2026-09'
  assert.notEqual(decisionKey(initial), decisionKey(reordered))
  assert.ok(!decisionKey(initial).includes('row'))
})

test('shared mappings scope wording, recorded year and category and cannot contain requirement-year decisions', () => {
  const shared: ReviewDecision = { kind: 'alias', context: { label: 'Historical wording (Elective)', recorded_year: 'R3', category: 'elective' }, target: decision().target }
  assert.notEqual(decisionKey(shared), decisionKey({ ...shared, context: { ...shared.context, recorded_year: 'R2' } }))
  assert.notEqual(decisionKey(shared), decisionKey({ ...shared, context: { ...shared.context, category: 'core' } }))
  assert.throws(() => parseReviewStore(JSON.stringify({ version: 1, decisions: [{ ...shared, requirement_year: 'R2' }] })), /invalid|unexpected/)
})

test('invalid, duplicate and unsupported JSON imports fail before any saved decisions change', () => {
  const original = store()
  for (const invalid of ['{', '{"version":2,"decisions":[]}', '{"version":1,"decisions":[null]}',
    JSON.stringify({ version: 1, decisions: [{ ...decision(), unexpected: true }] }),
    JSON.stringify({ version: 1, decisions: [decision(), decision()] }),
    JSON.stringify({ version: 1, decisions: [{ ...decision(), requirement_year: 'R6' }] })]) assert.throws(() => parseReviewStore(invalid))
  const badMonth = decision()
  if (badMonth.kind === 'resident') badMonth.context.months[0].month = '2026-19'
  assert.throws(() => parseReviewStore(JSON.stringify({ version: 1, decisions: [badMonth] })), /dates/)
  assert.deepEqual(original, store())
})

test('JSON conflicts reject the entire merge with actionable scope details and no overwrite', () => {
  const current = store()
  const replacement = decision()
  replacement.target = { key: 'another-entry', signature: 'different' }
  assert.throws(() => mergeReviewStores(current, { version: 1, decisions: [replacement] }), /Conflicting decision for M001.*Nothing was imported/)
  assert.deepEqual(current, store())
  assert.deepEqual(mergeReviewStores(current, store()), current)
})

test('corrupt and unavailable storage are surfaced; failed writes preserve the earlier saved data', () => {
  const browser = storage()
  browser.setItem(STORAGE_KEY, '{broken')
  const unreadable = readReviewStore(browser)
  assert.match(unreadable.error, /could not be read/)
  assert.deepEqual(unreadable.store, emptyStore())
  assert.equal(browser.getItem(STORAGE_KEY), '{broken')
  assert.match(readReviewStore({ getItem: () => { throw new Error('disabled') } }).error, /could not be read/)
  writeReviewStore(browser, store())
  const before = browser.getItem(STORAGE_KEY)
  assert.throws(() => writeReviewStore({ setItem: () => { throw new Error('QuotaExceededError') } }, emptyStore()), /not saved.*previous decisions are unchanged/i)
  assert.equal(browser.getItem(STORAGE_KEY), before)
})

test('review API sends structured decisions and surfaces malformed or unavailable responses', async (t) => {
  const workbook = { histories: [], postings: { core: [], electives: [] } } as unknown as Workbook
  const result = { entries: [], catalogue: [], decisions: [] }
  t.mock.method(globalThis, 'fetch', async (url: string, init: RequestInit) => {
    assert.equal(url, '/api/history-review')
    assert.equal(init.method, 'POST')
    assert.deepEqual(JSON.parse(String(init.body)), { workbook, store: store() })
    return Response.json(result)
  })
  assert.deepEqual(await evaluateHistory(workbook, store()), result)
  t.mock.method(globalThis, 'fetch', async () => Response.json({ detail: 'Import the workbook again.' }, { status: 422 }))
  await assert.rejects(evaluateHistory(workbook, store()), /Import the workbook again/)
  t.mock.method(globalThis, 'fetch', async () => { throw new Error('Network') })
  await assert.rejects(evaluateHistory(workbook, store()), /Could not reach/)
})


test('history queue excludes automatic matches, shows them under All entries and keeps unresolved reasons visible', () => {
  const entry = (status: string): HistoryEntry => ({
    id: status, key: status, name: 'Alex Example', mcr: 'SYN001', recorded_year: 'R1', identity_safe: true,
    months: [{ month: '2026-07', value: 'SITE Ward' }], sources: [],
    context: { mcr: 'SYN001', name: 'alex example', recorded_year: 'r1', months: [{ month: '2026-07', value: 'SITE Ward' }] },
    match: { status: 'matched', reasons: [], candidates: [] },
    review: { status, reasons: status === 'needs_review' ? ['catalogue_target_changed_or_missing'] : [], target: ['automatic_match', 'reviewed', 'label_confirmed', 'credit_review_required'].includes(status) ? { key: 'reference', signature: 'content', source: { sheet: 'Reference', row: 2 }, category: 'core', residency_year: 'R1', label: 'SITE Ward' } : null, requirement_year: null },
  })
  const rows = ['automatic_match', 'reviewed', 'unreviewed', 'label_confirmed', 'needs_review', 'credit_review_required'].map(entry)
  assert.deepEqual(rows.filter((row) => matchesHistoryFilter(row, 'open', '')).map((row) => row.review.status), ['unreviewed', 'needs_review'])
  assert.deepEqual(rows.filter((row) => matchesHistoryFilter(row, 'all', '')), rows)
  assert.deepEqual(rows.filter((row) => matchesHistoryFilter(row, 'reviewed', '')).map((row) => row.review.status), ['reviewed'])
  assert.equal(matchesHistoryFilter(rows[0], 'all', '  site WARD '), true)
  assert.equal(matchesHistoryFilter(rows[0], 'all', 'Missing'), false)
  assert.equal(historyStatusLabel(rows[0].review.status), 'Automatically matched')
  assert.equal(historyStatusLabel(rows[2].review.status), 'Needs review')
  assert.equal(historyStatusLabel(rows[3].review.status), 'Label confirmed - year open')
  assert.equal(historyStatusLabel(rows[4].review.status), 'Saved decision needs review')
  assert.deepEqual(rows[4].review.reasons, ['catalogue_target_changed_or_missing'])
  assert.equal(rows[0].review.requirement_year, null)
  const missingTarget = entry('label_confirmed')
  missingTarget.review.target = null
  assert.equal(matchesHistoryFilter(missingTarget, 'open', ''), true)
  const invalidSaved = entry('needs_review')
  invalidSaved.review.target = rows[0].review.target
  assert.equal(matchesHistoryFilter(invalidSaved, 'open', ''), true)
})


test('recognized remediation leaves the label queue but retains its credit status under All entries', () => {
  const entry = {
    name: 'Alex Example', mcr: 'SYN001', months: [{ month: '2026-07', value: 'SITE Ward (Remediation)' }],
    recorded_year: 'R2,R3', review: { status: 'credit_review_required', target: { category: 'core', residency_year: 'R1', label: 'SITE Ward' }, requirement_year: null, reasons: ['remediation_credit_review'] },
  } as HistoryEntry
  assert.equal(matchesHistoryFilter(entry, 'open', ''), false)
  assert.equal(matchesHistoryFilter(entry, 'all', ''), true)
  assert.equal(matchesHistoryFilter(entry, 'reviewed', ''), false)
  assert.equal(historyStatusLabel(entry.review.status), 'Remediation credit review')
  assert.equal(entry.review.requirement_year, null)
  assert.match(entry.months[0].value, /Remediation/)
  assert.equal(entry.recorded_year, 'R2,R3')
})
