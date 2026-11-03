import assert from 'node:assert/strict'
import test from 'node:test'
import type { Resident } from '../src/lib/workbook.ts'
import type { HistoryEntry } from '../src/lib/history-review.ts'
import { DEFAULT_POSTING_LABEL_MODE, groupPostings, postingCategory, postingDisplay } from '../src/lib/posting-blocks.ts'

const posting = (month: string, value: string | null, column: string, status: Resident['postings'][number]['status'] = 'posting') => ({ month, value, status, source: { sheet: 'Fictional timetable', row: 7, column } })

test('merges only consecutive months with exactly equal values, including across the year boundary', () => {
  const postings = [posting('2027-11', 'General Psychiatry', 'E'), posting('2027-12', 'General Psychiatry', 'F'), posting('2028-01', 'General Psychiatry', 'G'), posting('2028-02', 'General psychiatry', 'H'), posting('2028-03', 'General Psychiatry', 'I'), posting('2028-05', 'General Psychiatry', 'K')]
  const blocks = groupPostings(postings)
  assert.deepEqual(blocks.map((block) => block.length), [3, 1, 1, 1])
  assert.deepEqual(blocks.flat(), postings)
  blocks.flat().forEach((entry, index) => {
    assert.equal(entry, postings[index])
    assert.equal(entry.source, postings[index].source)
  })
  assert.equal(postings.length, 6)
})

test('keeps blank gaps separate from surrounding postings and preserves their original values and sources', () => {
  const postings = [posting('2027-07', 'Core', 'E'), posting('2027-08', null, 'F', 'blank'), posting('2027-09', '  ', 'G', 'blank'), posting('2027-10', '', 'H', 'blank'), posting('2027-11', 'Core', 'I')]
  assert.deepEqual(groupPostings(postings), [[postings[0]], [postings[1], postings[2], postings[3]], [postings[4]]])
  assert.deepEqual(groupPostings([]), [])
})


test('groups LOA variants by status while retaining raw entries and requiring consecutive months', () => {
  const postings = [posting('2027-11', 'LOA', 'E', 'loa'), posting('2027-12', ' loa ', 'F', 'loa'), posting('2028-01', 'LoA', 'G', 'loa'), posting('2028-02', 'LOA pending', 'H'), posting('2028-03', 'Repeat R3 TBC', 'I'), posting('2028-04', 'LOA', 'J', 'loa'), posting('2028-06', 'LOA', 'L', 'loa')]
  const blocks = groupPostings(postings)
  assert.deepEqual(blocks.map((block) => block.length), [3, 1, 1, 1, 1])
  assert.deepEqual(blocks.flat(), postings)
  blocks.flat().forEach((entry, index) => assert.equal(entry, postings[index]))
})

test('status boundaries prevent grouping equal raw labels', () => {
  const postings = [posting('2027-07', 'LOA', 'E', 'loa'), posting('2027-08', 'LOA', 'F'), posting('2027-09', '', 'G'), posting('2027-10', '', 'H', 'blank')]
  assert.equal(groupPostings(postings).length, 4)
})


function resolved(postings: Resident['postings'], status = 'automatic_match', label = 'SITE Department'): HistoryEntry {
  return {
    id: 'synthetic', key: 'period', name: 'Alex Example', mcr: 'SYN001', recorded_year: 'R3', identity_safe: true,
    months: postings.map((posting) => ({ month: posting.month, value: posting.value || '' })), sources: postings.map((posting) => posting.source),
    context: { mcr: 'SYN001', name: 'alex example', recorded_year: 'r3', months: postings.map((posting) => ({ month: posting.month, value: posting.value || '' })) },
    match: { status: 'matched', reasons: [], candidates: [] },
    review: { status, reasons: [], requirement_year: null, target: { key: label, signature: 'catalogue-content', category: 'core', residency_year: 'R2', label, source: { sheet: 'Reference', row: 2 } } },
  }
}

test('Catalogue is the default; Original remains available without changing raw block boundaries', () => {
  const postings = [posting('2027-07', '  site  department ', 'G'), posting('2027-08', '  site  department ', 'H'), posting('2027-09', 'SITE DEPARTMENT', 'I')]
  const original = structuredClone(postings)
  const blocks = groupPostings(postings)
  const entries = blocks.map((block) => resolved(block))
  assert.equal(DEFAULT_POSTING_LABEL_MODE, 'catalogue')
  assert.deepEqual(postingDisplay(blocks[0], undefined, entries), { label: 'SITE Department', canonical: true, markers: [] })
  assert.equal(postingDisplay(blocks[0]).label, '  site  department ')
  assert.equal(postingDisplay(blocks[0], 'original', entries).label, '  site  department ')
  assert.deepEqual(postingDisplay(blocks[0], 'catalogue', entries), { label: 'SITE Department', canonical: true, markers: [] })
  assert.deepEqual(blocks.map((block) => block.length), [2, 1])
  assert.deepEqual(postings, original)
})

test('Catalogue keeps elective and remediation markers separate from the exact canonical label', () => {
  const block = [posting('2027-07', 'Legacy wording( eLeCtIvE ) (Remediation)', 'G')]
  const entry = resolved(block, 'credit_review_required')
  entry.review.target!.category = 'elective'
  assert.deepEqual(postingDisplay(block, 'catalogue', [entry]), { label: 'SITE Department', canonical: true, markers: ['Elective', 'Remediation'] })
  assert.equal(block[0].value, 'Legacy wording( eLeCtIvE ) (Remediation)')
  for (const status of ['label_confirmed', 'reviewed']) {
    entry.review.status = status
    assert.equal(postingDisplay(block, 'catalogue', [entry]).label, 'SITE Department')
  }
})

test('Unresolved, stale/conflicting, partial or inconsistent resolutions preserve the original label', () => {
  const block = [posting('2027-07', 'Original wording', 'G'), posting('2027-08', 'Original wording', 'H')]
  for (const status of ['unreviewed', 'needs_review']) {
    assert.deepEqual(postingDisplay(block, 'catalogue', [resolved(block, status)]), { label: 'Original wording', canonical: false, markers: [] })
  }
  assert.equal(postingDisplay(block, 'catalogue', []).canonical, false)
  assert.equal(postingDisplay(block, 'catalogue', [resolved(block.slice(0, 1))]).canonical, false)
  assert.equal(postingDisplay(block, 'catalogue', [resolved(block.slice(0, 1)), resolved(block.slice(1), 'reviewed', 'Other exact target')]).canonical, false)
  const unrelated = resolved(structuredClone(block))
  unrelated.sources.forEach((source) => { source.row += 1 })
  assert.equal(postingDisplay(block, 'catalogue', [unrelated]).canonical, false)
})

test('LOA and blank display are unchanged in both modes, even with a supplied catalogue resolution', () => {
  for (const [status, value, expected] of [['loa', ' loa ', 'LOA'], ['blank', null, 'Unallocated']] as const) {
    const block = [posting('2027-07', value, 'G', status)]
    for (const mode of ['original', 'catalogue'] as const) {
      assert.deepEqual(postingDisplay(block, mode, [resolved(block)]), { label: expected, canonical: false, markers: [] })
    }
    assert.equal(block[0].value, value)
    assert.equal(block[0].status, status)
  }
})


test('elective styling metadata comes from a resolved catalogue category and stays out of Original mode', () => {
  const block = [posting('2027-07', 'Legacy wording', 'G')]
  const entry = resolved(block, 'label_confirmed')
  entry.review.target!.category = 'elective'
  assert.deepEqual(postingDisplay(block, 'catalogue', [entry]).markers, ['Elective'])
  assert.deepEqual(postingDisplay(block, 'original', [entry]).markers, [])
  entry.review.status = 'needs_review'
  assert.deepEqual(postingDisplay(block, 'catalogue', [entry]).markers, [])
  block[0].value = 'Unresolved wording (Elective)'
  assert.deepEqual(postingDisplay(block, 'catalogue', []).markers, [])
})


test('Catalogue classifies resolved core/elective, unresolved, LOA and unallocated independently of wording', () => {
  const block = [posting('2027-07', 'Original wording', 'G')]
  const entry = resolved(block)
  assert.equal(postingCategory(postingDisplay(block, 'catalogue', [entry]), 'posting'), 'core')
  entry.review.target!.category = 'elective'
  assert.equal(postingCategory(postingDisplay(block, 'catalogue', [entry]), 'posting'), 'elective')
  entry.review.status = 'needs_review'
  const unresolved = postingDisplay(block, 'catalogue', [entry])
  assert.equal(postingCategory(unresolved, 'posting'), 'unresolved')
  assert.equal(postingCategory(unresolved, 'loa'), 'loa')
  assert.equal(postingCategory(unresolved, 'blank'), 'unallocated')
})
