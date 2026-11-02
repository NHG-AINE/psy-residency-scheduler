import assert from 'node:assert/strict'
import test from 'node:test'
import { groupPostings } from '../src/lib/posting-blocks.ts'

const posting = (month: string, value: string | null, column: string) => ({ month, value, source: { sheet: 'Fictional timetable', row: 7, column } })

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
  const postings = [posting('2027-07', 'Core', 'E'), posting('2027-08', null, 'F'), posting('2027-09', null, 'G'), posting('2027-10', '', 'H'), posting('2027-11', 'Core', 'I')]
  assert.deepEqual(groupPostings(postings), [[postings[0]], [postings[1], postings[2]], [postings[3]], [postings[4]]])
  assert.deepEqual(groupPostings([]), [])
})
