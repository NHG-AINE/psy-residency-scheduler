import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import type { RequestOutcome } from '../src/lib/draft-schedule.ts'

test('Request details render compact calendar ranges and keep meaningful durations', async () => {
  const vite = await createServer({ server: { middlewareMode: true, ws: false }, appType: 'custom' })
  try {
    const { RequestOutcomeDetails } = await vite.ssrLoadModule('/src/components/RequestDetails.tsx')
    const source = { sheet: 'Requests', row: 2 }
    const outcome = (period: string | null, requested_months: number, extra: Partial<RequestOutcome> = {}): RequestOutcome => ({
      request: { posting_request: 'IMH Elective', period, source }, status: 'not_met', requested_months, ...extra,
    })
    const render = (row: RequestOutcome) => renderToStaticMarkup(createElement(RequestOutcomeDetails, { row }))

    for (const [row, expected] of [
      [outcome('July - December 2027', 6), 'Jul–Dec 2027'],
      [outcome('Jul - Dec 2027', 3), 'Jul–Dec 2027 · 3 months'],
      [outcome('Jul - Dec 2027', 6, { requested_durations: [3, 6] }), 'Jul–Dec 2027 · 3 or 6 months'],
      [outcome('October 2027 – March 2028', 6), 'Oct 2027–Mar 2028'],
      [outcome('Jul – July 2027', 1), 'Jul 2027'],
      [outcome('July 2027', 1), 'Jul 2027'],
      [outcome(null, 6), 'Any time in planning year · 6 months'],
      [outcome('After exams', 3), 'After exams · 3 months'],
      [outcome('July - December 2027', 6, { status: 'pending', reason: 'Period is unclear or outside the planning year' }), 'July - December 2027 · 6 months'],
    ] as const) {
      assert.ok(render(row).includes(`<small>${expected}</small>`), expected)
    }

    const capacity = { requirement_id: 'r5.elective', institution: 'IMH', label: 'IMH Elective', source,
      residency_year: 'R5', category: 'elective' as const, max: 2, assigned: 2 }
    const html = render(outcome('Jul - Dec 2027', 5, {
      assigned: [{ label: 'Assigned Elective', months: ['2027-12', '2027-07', '2027-08', '2027-09', '2027-11'] }],
      capacity: ['2027-09', '2027-10', '2027-12', '2028-01'].map((month) => ({ ...capacity, month })),
    }))
    assert.match(html, /Requested<\/dt>.*<small>Jul–Dec 2027 · 5 months<\/small>/)
    assert.match(html, /Assigned<\/dt>.*<small>Jul–Sep 2027, Nov–Dec 2027<\/small>/)
    assert.match(html, /Capacity in this draft.*<span>Sep–Oct 2027<\/span>.*<span>Dec 2027–Jan 2028<\/span>/)

    const alternatives = render(outcome(null, 6, { status: 'met', alternatives: [
      outcome('July - September 2027', 3, { status: 'met' }), outcome('October - December 2027', 1),
    ] }))
    assert.match(alternatives, /Requested alternatives<\/dt>.*<small>Jul–Sep 2027<\/small>.*Selected.*<small>OR<\/small>.*<small>Oct–Dec 2027 · 1 month<\/small>/)
  } finally {
    await vite.close()
  }
})
