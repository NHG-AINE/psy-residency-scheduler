import assert from 'node:assert/strict'
import test from 'node:test'
import { draftTiming } from '../src/lib/draft-timing.ts'
import type { DraftSchedule } from '../src/lib/draft-schedule.ts'

test('timeline follows returned priorities and distinguishes unproven, unknown and unreached stages', () => {
  const stages = draftTiming({
    soft_priority: ['resident_requests', 'posting_balance', 'inpatient_allocation', 'singleton_months'],
    optimisation_stages: [
      { priority: 'posting_balance', status: 'feasible', wall_time_seconds: 10 },
      { priority: 'resident_requests', status: 'optimal', wall_time_seconds: 2 },
      { priority: 'inpatient_allocation', status: 'unknown', wall_time_seconds: 4 },
    ],
  } as DraftSchedule)
  assert.deepEqual(stages.map(({ outcome, seconds }) => [outcome, seconds]), [
    ['Optimal', 2], ['Best found - not proven', 10], ['No new solution', 4], ['Not reached', undefined],
  ])
  assert.equal(stages.some(({ priority }) => priority === 'r3_missing_clusters'), false)
})

test('older drafts need no diagnostics and nested smaller-model time is not counted twice', () => {
  assert.deepEqual(draftTiming({} as DraftSchedule), [])
  const draft = { optimisation_stages: [{ priority: 'monthly_medicine_neurology_ratio', status: 'optimal', wall_time_seconds: 12, ratio_relaxation: { wall_time_seconds: 2 } }] }
  const stages = draftTiming(draft as DraftSchedule)
  assert.equal(stages.length, 1)
  assert.equal(stages[0].seconds, 12)
})


test('initial draft is shown before preferences without claiming preference optimality', () => {
  const draft = {
    soft_priority: ['incoming_route_distribution', 'resident_requests'],
    optimisation_stages: [
      { priority: 'initial_feasibility', status: 'feasible', wall_time_seconds: 4 },
      { priority: 'incoming_route_distribution', status: 'unknown', wall_time_seconds: 2 },
    ],
  } as DraftSchedule
  const stages = draftTiming(draft)
  assert.deepEqual(stages.map(({ priority, outcome, complete }) => [priority, outcome, complete]), [
    ['initial_feasibility', 'Valid draft found', true],
    ['incoming_route_distribution', 'No new solution', false],
    ['resident_requests', 'Not reached', false],
  ])
  assert.equal(stages[0].label, 'Find initial draft')
  assert.equal(stages.reduce((total, stage) => total + (stage.seconds || 0), 0), 6)
  draft.soft_priority = ['initial_feasibility', ...draft.soft_priority!]
  assert.equal(draftTiming(draft).length, 3)
  draft.optimisation_stages![0].status = 'unknown'
  assert.equal(draftTiming(draft)[0].outcome, 'No draft found')
  assert.equal(draftTiming(draft)[0].complete, false)
})
