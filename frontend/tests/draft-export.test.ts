import assert from 'node:assert/strict'
import test from 'node:test'
import { exportDraft, downloadDraft } from '../src/lib/draft-export.ts'
import { parseSession } from '../src/lib/workbook-session.ts'
import type { DraftSchedule } from '../src/lib/draft-schedule.ts'

const draft = { status: 'feasible', cutoff: '2027-06', blockers: [], residents: [
  { source: { sheet: 'Latest', row: 3 }, name: 'Visible', mcr: null, months: [], carryforward: [] },
  { source: { sheet: 'Latest', row: 4 }, name: 'Filtered out', mcr: null, months: [], carryforward: [] },
] } as DraftSchedule

test('export sends original restored workbook and every draft resident regardless of display filters', async () => {
  const restored = parseSession({ version: 1, file: new Blob(['original xlsx bytes']), fileName: 'Programme.xlsx', lastModified: 123,
    workbook: { target_year: 2027, available_years: [{ year: 2027, sheet: 'Latest' }], target_sheet: 'Latest', months: [], residents: [], histories: [], requests: [], warnings: [], postings: { core: [], rows: [] } }, draft: null })!
  const before = structuredClone(draft)
  const fetch = globalThis.fetch
  try {
    globalThis.fetch = async (url, init) => {
      assert.equal(url, '/api/export')
      assert.equal(init?.method, 'POST')
      const form = init?.body as FormData
      const file = form.get('originalFile') as File
      assert.equal(file.name, 'Programme.xlsx')
      assert.equal(await file.text(), 'original xlsx bytes')
      assert.equal(form.get('target_year'), '2027')
      assert.deepEqual(JSON.parse(form.get('draft') as string), draft)
      return new Response(new Blob(['exported bytes']))
    }
    const result = await exportDraft(restored.file, 2027, draft)
    assert.equal(await result.blob.text(), 'exported bytes')
    assert.deepEqual(result.retainedResidents, [])
    globalThis.fetch = async () => new Response(new Blob(['exported bytes']), { headers: { 'X-Export-Retained-Residents': JSON.stringify(['Preserved Resident']) } })
    assert.deepEqual((await exportDraft(restored.file, 2027, draft)).retainedResidents, ['Preserved Resident'])
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'Draft does not match workbook.' }), { status: 422 })
    await assert.rejects(exportDraft(restored.file, 2027, draft), /Draft does not match workbook/)
    globalThis.fetch = async () => { throw new TypeError('offline') }
    await assert.rejects(exportDraft(restored.file, 2027, draft), /Check the connection/)
    assert.deepEqual(draft, before)
  } finally { globalThis.fetch = fetch }
})

test('large edited drafts omit only the warning baseline from the export form', async () => {
  const target = { category: 'core' as const, requirement_id: 'r2.child_adolescent_psychiatry',
    residency_year: 'R2', institution: 'NUH', source: { sheet: 'Postings', row: 16, column: 'D' },
    label: 'NUH Child & Adolescent Psychiatry' }
  const months = Array.from({ length: 12 }, (_, index) => {
    const date = new Date(Date.UTC(2027, 6 + index, 1)).toISOString().slice(0, 7)
    return { month: date, status: 'posting' as const, block_start: date, label: target.label, target }
  })
  const residents = Array.from({ length: 165 }, (_, index) => ({
    source: { sheet: 'Jul 2027 - Jun 2028', row: index + 3 }, name: `Resident ${index + 1}`, mcr: null,
    months, carryforward: [],
  }))
  const capacity_overflows = months.map(({ month }) => ({ ...target, month, max: 24, assigned: residents.length,
    residents: residents.map(({ source, name, mcr }) => ({ source, name, mcr })) }))
  const baseline = { capacity_overflows, residents: residents.map(({ source }) => ({
    source, months: months.map(() => ({ ...target.source, row: 15 })),
  })) }
  const edited: DraftSchedule = { ...draft, status: 'edited', residents, capacity_overflows, edit_baseline: baseline }
  const partLimit = 1024 * 1024
  assert.ok(Buffer.byteLength(JSON.stringify(edited)) > partLimit)
  const fetch = globalThis.fetch
  const mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  let sent = ''
  try {
    globalThis.fetch = async (_, init) => {
      assert.ok(init?.body instanceof FormData)
      sent = init.body.get('draft') as string
      return Buffer.byteLength(sent) > partLimit
        ? new Response(JSON.stringify({ detail: 'Part exceeded maximum size of 1024KB.' }), { status: 400 })
        : new Response('xlsx', { headers: { 'Content-Type': mime } })
    }
    const exported = await exportDraft(new File(['original workbook'], 'Programme.xlsx'), 2027, edited)
    assert.equal(exported.blob.type, mime)
    assert.deepEqual(JSON.parse(sent), { ...draft, status: 'edited', residents, capacity_overflows })
    assert.equal(edited.edit_baseline, baseline)
  } finally { globalThis.fetch = fetch }
})

test('download uses draft filename and cleans the temporary link and URL on success or failure', () => {
  const savedDocument = Object.getOwnPropertyDescriptor(globalThis, 'document')
  const create = URL.createObjectURL, revoke = URL.revokeObjectURL, timer = globalThis.setTimeout
  const events: string[] = []
  let fail = false
  const link = { href: '', download: '', remove: () => { events.push('remove') }, click: () => { events.push('click'); if (fail) throw new Error('download failed') } }
  try {
    Object.defineProperty(globalThis, 'document', { configurable: true, value: { createElement: () => link, body: { append: () => { events.push('append') } } } })
    URL.createObjectURL = () => 'blob:test'
    URL.revokeObjectURL = (url) => { assert.equal(url, 'blob:test'); events.push('revoke') }
    globalThis.setTimeout = ((callback: () => void) => { callback(); return 1 }) as typeof setTimeout
    downloadDraft(new Blob(['xlsx']), 'Programme.XLSX', 2027)
    assert.equal(link.download, 'Programme - Draft 2027-2028.xlsx')
    assert.deepEqual(events, ['append', 'click', 'remove', 'revoke'])
    events.length = 0; fail = true
    assert.throws(() => downloadDraft(new Blob(['xlsx']), 'Programme.xlsx', 2027), /download failed/)
    assert.deepEqual(events, ['append', 'click', 'remove', 'revoke'])
  } finally {
    URL.createObjectURL = create; URL.revokeObjectURL = revoke; globalThis.setTimeout = timer
    if (savedDocument) Object.defineProperty(globalThis, 'document', savedDocument)
    else Reflect.deleteProperty(globalThis, 'document')
  }
})
