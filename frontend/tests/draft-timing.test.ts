import assert from 'node:assert/strict'
import test from 'node:test'
import { draftTiming } from '../src/lib/draft-timing.ts'
import type { DraftSchedule } from '../src/lib/draft-schedule.ts'

test('older drafts need no diagnostics and nested smaller-model time is not counted twice', () => {
  assert.deepEqual(draftTiming({} as DraftSchedule), [])
  const draft = { optimisation_stages: [{ priority: 'monthly_medicine_neurology_ratio', status: 'optimal', wall_time_seconds: 12, ratio_relaxation: { wall_time_seconds: 2 } }] }
  const stages = draftTiming(draft as DraftSchedule)
  assert.equal(stages.length, 1)
  assert.equal(stages[0].seconds, 12)
})
