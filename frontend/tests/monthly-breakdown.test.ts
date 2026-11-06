import assert from 'node:assert/strict'
import test from 'node:test'
import { monthlyBreakdown } from '../src/lib/monthly-breakdown.ts'
import type { Workbook, Resident } from '../src/lib/workbook.ts'
import type { DraftSchedule } from '../src/lib/draft-schedule.ts'

 test('breakdown uses draft overlays, posting requirement years for mixed-year residents, zero sites and full-cohort capacity counts', () => {
  const people = ['R1', 'R1,R2', 'R2'].map((residency_year, row) => ({
    residency_year, source: { sheet: 'Plan', row }, postings: [
      { month: '2027-07', value: 'old label', status: 'posting', source: { sheet: 'Plan', row, column: 'B' } },
      { month: '2027-08', value: row === 0 ? 'LOA' : null, status: row === 0 ? 'loa' : 'blank', source: { sheet: 'Plan', row, column: 'C' } },
    ],
  })) as Resident[]
  const workbook = { residents: people, months: [{ month: '2027-07' }, { month: '2027-08' }], postings: {
    core: [{ posting: 'IMH Inpatient Psychiatry', max: '9' }, { posting: 'NUH Inpatient Psychiatry', max: null }],
    electives: [{ institution: 'IMH', elective: 'Inpatient Psychiatry' }],
  } } as Workbook
  const draft = { status: 'optimal', residents: people.map((person, index) => ({ source: person.source, months: [
    { month: '2027-07', status: 'posting', label: 'IMH Inpatient Psychiatry', target: { category: index === 2 ? 'elective' : 'core', residency_year: index === 2 ? 'R2' : 'R1' } },
    { month: '2027-08', status: 'outside_draft_scope', label: null },
  ] })) } as DraftSchedule
  const before = structuredClone({ workbook, draft })
  const rows = monthlyBreakdown(workbook, draft, [], 'R1')
  const core = rows.find((row) => row.label === 'Inpatient Psychiatry')!
  assert.equal(core.counts['2027-07'], 2)
  assert.equal(core.institutions[0].allCounts['2027-07'], 2)
  assert.equal(core.institutions[0].capacity, 9)
  assert.deepEqual(core.institutions[1].counts, {})
  assert.equal(rows.find((row) => row.label === 'LOA')!.counts['2027-08'], 1)
  assert.equal(monthlyBreakdown(workbook, draft, [], 'R2').find((row) => row.label === 'Electives')!.counts['2027-07'], 1)
  const all = monthlyBreakdown(workbook, draft, [])
  assert.equal(all.find((row) => row.label === 'Inpatient Psychiatry (Elective)')!.counts['2027-07'], 1)
  assert.equal(all.find((row) => row.label === 'Unallocated')!.counts['2027-08'], 2)
  assert.equal(monthlyBreakdown(workbook, null, []).find((row) => row.label === 'Unresolved')!.counts['2027-07'], 3)
  assert.deepEqual({ workbook, draft }, before)
})
