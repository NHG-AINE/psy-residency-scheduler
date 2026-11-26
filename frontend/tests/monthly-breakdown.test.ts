import assert from 'node:assert/strict'
import test from 'node:test'
import { monthlyBreakdown } from '../src/lib/monthly-breakdown.ts'
import type { Workbook, Resident } from '../src/lib/workbook.ts'
import { draftPostings, type DraftSchedule } from '../src/lib/draft-schedule.ts'
import type { HistoryEntry } from '../src/lib/history-review.ts'

test('recorded completion replaces unallocated display and counts and yields to a live draft', () => {
  const [gap, leave, completed] = ['2027-07', '2027-08', '2027-09']
  const source = { sheet: 'Plan', row: 4 }
  const person = { residency_year: 'R5', source, postings: [gap, leave, completed].map((month, index) => ({
    month, value: month === leave ? 'LOA' : null, status: month === leave ? 'loa' : 'blank',
    source: { ...source, column: `M${index}` },
  })) } as Resident
  const workbook = { residents: [person], months: [gap, leave, completed].map((month) => ({ month })), postings: { core: [] } } as unknown as Workbook
  const completions = [{ source, months: [completed] }]
  const draft = { status: 'optimal', residents: [{ source, months: [
    { month: completed, status: 'posting', label: 'IMH Geriatric Psychiatry', target: { category: 'core', residency_year: 'R5' } },
  ] }] } as DraftSchedule
  assert.deepEqual(draftPostings(person, null, completions).map(({ status }) => status), ['blank', 'loa', 'requirements_completed'])
  assert.deepEqual(monthlyBreakdown(workbook, null, [], 'R5', completions).map(({ label, counts }) => [label, counts]), [
    ['LOA', { [leave]: 1 }], ['Unallocated', { [gap]: 1 }],
  ])
  assert.deepEqual(monthlyBreakdown(workbook, draft, [], 'R5', completions).map(({ label }) => label),
    ['Geriatric Psychiatry', 'LOA', 'Unallocated'])
  assert.equal(person.postings[2].status, 'blank')
})

test('breakdown uses draft overlays, posting requirement years for mixed-year residents, zero sites and full-cohort capacity counts', () => {
  const people = ['R1', 'R1,R2', 'R2'].map((residency_year, row) => ({
    residency_year, source: { sheet: 'Plan', row }, postings: [
      { month: '2027-07', value: 'old label', status: 'posting', source: { sheet: 'Plan', row, column: 'B' } },
      { month: '2027-08', value: row === 0 ? 'LOA' : null, status: row === 0 ? 'loa' : 'blank', source: { sheet: 'Plan', row, column: 'C' } },
    ],
  })) as Resident[]
  const workbook = { residents: people, months: [{ month: '2027-07' }, { month: '2027-08' }], postings: {
    core: [{ posting: 'IMH Inpatient Psychiatry', residency_year: 'R1', max: '9' }, { posting: 'NUH Inpatient Psychiatry', residency_year: 'R1', max: null }],
    electives: [{ institution: 'IMH', elective: 'Inpatient Psychiatry', residency_year: 'R2' }],
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
  assert.deepEqual(core.institutions[0].overflows, [])
  assert.deepEqual(core.institutions[1].counts, {})
  assert.equal(rows.find((row) => row.label === 'LOA')!.counts['2027-08'], 1)
  assert.equal(monthlyBreakdown(workbook, draft, [], 'R2').find((row) => row.label === 'Electives')!.counts['2027-07'], 1)
  const all = monthlyBreakdown(workbook, draft, [])
  assert.equal(all.find((row) => row.label === 'Inpatient Psychiatry (Elective)')!.counts['2027-07'], 1)
  assert.equal(all.find((row) => row.label === 'Unallocated')!.counts['2027-08'], 2)
  assert.equal(monthlyBreakdown(workbook, null, []).find((row) => row.label === 'Unresolved')!.counts['2027-07'], 3)
  assert.deepEqual({ workbook, draft }, before)
})


test('R2 and R5 electives share one expandable group with separate posting rows and year-specific totals', () => {
  const people = ['R2', 'R5', 'R4,R5'].map((residency_year, row) => ({ residency_year,
    source: { sheet: 'Plan', row }, postings: [{ month: '2027-07', value: null, status: 'blank', source: { sheet: 'Plan', row, column: 'B' } }],
  })) as Resident[]
  const workbook = { residents: people, months: [{ month: '2027-07' }], postings: {
    core: [], electives: [
      { residency_year: 'R2', institution: 'CGH', elective: 'Inpatient Psychiatry' },
      { residency_year: 'R5', institution: 'IMH', elective: 'Addiction Medicine' },
      { residency_year: 'R5', institution: 'NUH', elective: 'Consultation Liaison' },
      { residency_year: 'R2, R5', institution: 'AH', elective: 'Consultation Liaison' },
    ],
  } } as unknown as Workbook
  const labels = ['CGH Inpatient Psychiatry', 'IMH Addiction Medicine', 'NUH Consultation Liaison']
  const draft = { status: 'optimal', residents: people.map((person, index) => ({ source: person.source,
    months: [{ month: '2027-07', status: 'posting', label: labels[index], target: { category: 'elective', residency_year: index === 0 ? 'R2' : 'R5' } }],
  })) } as DraftSchedule
  for (const year of ['R2', 'R5']) {
    const groups = monthlyBreakdown(workbook, draft, [], year)
    assert.equal(groups.length, 1)
    assert.equal(groups[0].label, 'Electives')
    assert.equal(groups[0].counts['2027-07'], year === 'R2' ? 1 : 2)
    const assigned = year === 'R2' ? labels.slice(0, 1) : labels.slice(1)
    assert.deepEqual(groups[0].institutions.map((site) => [site.label, site.counts['2027-07'] || 0]),
      [['AH Consultation Liaison', 0], ...assigned.map((label) => [label, 1])])
  }
})

function resolved(person: Resident, year: string, requirementYear: string | null = null): HistoryEntry {
  const months = person.postings.map(({ month, value }) => ({ month, value: value! }))
  const target = { key: 'clinic', signature: 'catalogue-content', category: 'core' as const,
    residency_year: year, label: 'TTSH Continuity Clinic', source: { sheet: 'Postings', row: 2 } }
  return {
    id: `clinic-${person.source.row}`, key: `clinic-${person.source.row}`, name: person.name, mcr: person.mcr,
    recorded_year: person.residency_year, identity_safe: true, months, sources: person.postings.map(({ source }) => source),
    context: { mcr: person.mcr || '', name: person.name || '', recorded_year: person.residency_year || '', months },
    match: { status: 'matched', reasons: [], candidates: [] },
    review: { status: requirementYear ? 'reviewed' : 'automatic_match', reasons: [], target, requirement_year: requirementYear },
  }
}

test('R4 catch-up Continuity Clinic counts once in R3 at its institution in imported and draft timetables', () => {
  const month = '2027-07'
  const person = { residency_year: 'R4', source: { sheet: 'Plan', row: 4 }, postings: [
    { month, value: 'TTSH CC', status: 'posting', source: { sheet: 'Plan', row: 4, column: 'B' } },
  ] } as Resident
  const workbook = { residents: [person], months: [{ month }], postings: {
    core: [{ posting: 'TTSH Continuity Clinic', residency_year: 'R3' }, { posting: 'IMH Continuity Clinic', residency_year: 'R3' }],
  } } as unknown as Workbook
  const draft = { status: 'optimal', residents: [{ source: person.source, projected_year: 'R4',
    months: [{ month, status: 'posting', label: 'TTSH Continuity Clinic', target: { category: 'core', residency_year: 'R3' } }],
  }] } as DraftSchedule
  for (const [schedule, entries] of [[null, [resolved(person, 'R3')]], [draft, []]] as const) {
    const clinic = (year?: string) => monthlyBreakdown(workbook, schedule, [...entries], year).find((group) => group.label === 'Continuity Clinic')
    assert.equal(clinic('R3')?.counts[month], 1)
    assert.deepEqual(clinic('R3')?.institutions.map((site) => [site.label, site.counts[month] || 0]), [['IMH', 0], ['TTSH', 1]])
    assert.equal(clinic('R4'), undefined)
    assert.equal(clinic()?.counts[month], 1)
    assert.equal(['R1', 'R2', 'R3', 'R4', 'R5'].reduce((sum, year) => sum + (clinic(year)?.counts[month] || 0), 0), 1)
  }
})

test('shared catalogue labels use a reviewed or unique eligible cohort year, with ambiguous rows unresolved', () => {
  const month = '2027-07'
  const people = ['R4', 'R3,R4', 'R1,R3', 'R4'].map((residency_year, row) => ({ residency_year,
    source: { sheet: 'Plan', row }, postings: [{ month, value: 'TTSH CC', status: 'posting', source: { sheet: 'Plan', row, column: 'B' } }],
  })) as Resident[]
  const workbook = { residents: people, months: [{ month }], postings: { core: [] } } as unknown as Workbook
  const entries = people.map((person, index) => resolved(person, 'R1,R3', index === 0 ? 'R3' : null))
  const rows = (year?: string) => monthlyBreakdown(workbook, null, entries, year).map(({ label, counts }) => [label, counts[month]])
  assert.deepEqual(rows('R3'), [['Continuity Clinic', 2]])
  assert.deepEqual(rows('R1'), [['Unresolved', 1]])
  assert.deepEqual(rows('R4'), [['Unresolved', 1]])
  assert.deepEqual(rows(), [['Continuity Clinic', 2], ['Unresolved', 2]])
})

test('older drafts with a missing target year fall back to the same cohort as LOA and unallocated months', () => {
  const months = ['2027-07', '2027-08', '2027-09']
  const person = { residency_year: 'R3', source: { sheet: 'Plan', row: 4 }, postings: months.map((month, index) => ({
    month, value: index === 1 ? 'LOA' : null, status: index === 1 ? 'loa' : 'blank', source: { sheet: 'Plan', row: 4, column: `M${index}` },
  })) } as Resident
  const workbook = { residents: [person], months: months.map((month) => ({ month })), postings: { core: [] } } as unknown as Workbook
  const draft = { status: 'optimal', residents: [{ source: person.source, projected_year: 'R4,R5',
    months: [{ month: months[0], status: 'posting', label: 'TTSH Continuity Clinic' }],
  }] } as DraftSchedule
  assert.deepEqual(monthlyBreakdown(workbook, draft, [], 'R3'), [])
  assert.deepEqual(monthlyBreakdown(workbook, draft, [], 'R4').map(({ label, counts }) => [label, counts]), [
    ['Continuity Clinic', { [months[0]]: 1 }], ['LOA', { [months[1]]: 1 }], ['Unallocated', { [months[2]]: 1 }],
  ])
  assert.deepEqual(monthlyBreakdown(workbook, draft, [], 'R5'), [])
})

test('capacity warnings use exact requirement identity and retain full names across recorded cohorts', () => {
  const sources = [{ sheet: 'Postings', row: 2, column: 'A' }, { sheet: 'Postings', row: 2, column: 'B' }]
  const people = ['R1', 'R5', 'R4', 'R4'].map((residency_year, row) => ({ name: `Person ${row}`, residency_year,
    source: { sheet: 'Plan', row }, postings: [{ month: '2027-07', value: null, status: 'blank', source: { sheet: 'Plan', row, column: 'B' } }],
  })) as Resident[]
  const workbook = { residents: people, months: [{ month: '2027-07' }], postings: { core: [
    ...sources.map((source, i) => ({ source, posting: 'IMH Inpatient Psychiatry', residency_year: i ? 'R4' : 'R1', max: i ? '9' : '1' })),
    { posting: 'TTSH Inpatient Psychiatry', residency_year: 'R1, R3' },
    { posting: 'SGH Inpatient Psychiatry', residency_year: 'R4' },
    { posting: 'NUH Inpatient Psychiatry', residency_year: 'R4' },
  ], electives: [] } } as unknown as Workbook
  const overflow = { month: '2027-07', requirement_id: 'r1.inpatient_psychiatry', institution: 'IMH', label: 'IMH Inpatient Psychiatry',
    source: sources[0], residency_year: 'R1', category: 'core' as const, max: 1, assigned: 2, residents: people.slice(0, 2),
  }
  const draft = { status: 'optimal', capacity_overflows: [overflow], residents: people.map((person, i) => ({ source: person.source,
    months: [{ month: '2027-07', status: 'posting', label: i === 3 ? 'SGH Inpatient Psychiatry' : overflow.label, target: { source: sources[i >= 2 ? 1 : 0], category: 'core', residency_year: i >= 2 ? 'R4' : 'R1' } }],
  })) } as unknown as DraftSchedule
  const r1 = monthlyBreakdown(workbook, draft, [], 'R1')[0].institutions
  assert.deepEqual(r1.map((site) => site.label), ['IMH', 'TTSH'])
  assert.equal(r1[0].counts['2027-07'], 2)
  assert.equal(r1[0].allCounts['2027-07'], 3)
  assert.deepEqual(r1[0].overflows, [overflow])
  assert.deepEqual(r1[0].overflows[0].residents.map((person) => person.name), ['Person 0', 'Person 1'])
  assert.deepEqual(monthlyBreakdown(workbook, draft, [], 'R5'), [])
  const r4 = monthlyBreakdown(workbook, draft, [], 'R4')[0].institutions
  assert.deepEqual(r4.map((site) => site.label), ['IMH', 'NUH', 'SGH'])
  assert.equal(r4[0].counts['2027-07'], 1)
  assert.deepEqual(r4[0].overflows, [])
  assert.equal(draft.capacity_overflows!.length, 1) // Summary stays independent of selected cohort/search.
})
