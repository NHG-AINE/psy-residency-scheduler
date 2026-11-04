import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'
import { applyIntakeLinks, emptyIntakeStore, INTAKE_STORAGE_KEY, makeIntakeLink, mergeIntakeStores, parseIntakeStore, readIntakeStore, writeIntakeStore } from '../src/lib/intake-links.ts'
import type { IntakeLinkStore } from '../src/lib/intake-links.ts'
import type { Resident, Workbook } from '../src/lib/workbook.ts'

const saved = (): IntakeLinkStore => ({ version: 1, links: [{ year: 2027, slot_id: 'intake-2027-slot-02', name: 'Incoming Example', mcr: 'M900',
  postings: [{ month: '2027-07', value: 'TTSH General Medicine', status: 'posting', source: { sheet: 'Planning', row: 4, column: 'G' } }] }] })
const memory = () => {
  const values = new Map<string, string>()
  return { values, getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) } }
}

test('intake links survive storage and JSON backup without changing identities or slot postings', () => {
  const storage = memory(), store = saved()
  writeIntakeStore(storage, store, emptyIntakeStore())
  assert.deepEqual(readIntakeStore(storage), store)
  assert.deepEqual(parseIntakeStore(JSON.stringify(store)), store)
  assert.deepEqual(mergeIntakeStores(store, parseIntakeStore(JSON.stringify(store))), store)
  const slot = { slot_id: store.links[0].slot_id, postings: store.links[0].postings } as Resident
  assert.deepEqual(makeIntakeLink(2027, { name: 'Incoming Example', mcr: 'M900' } as Resident, slot), store.links[0])
})

test('duplicate scopes and malformed snapshot imports fail atomically', () => {
  const store = saved()
  const conflicting = saved(); conflicting.links[0].name = 'Conflicting name'
  assert.throws(() => mergeIntakeStores(store, conflicting), /Duplicate or conflicting/)
  const variants = [
    (value: IntakeLinkStore) => { value.links.push({ ...value.links[0], slot_id: 'intake-2027-slot-03' }) },
    (value: IntakeLinkStore) => { value.links[0].postings[0].month = '2026-07' },
    (value: IntakeLinkStore) => { value.links[0].postings[0].status = 'loa' },
    (value: IntakeLinkStore) => { value.links[0].postings.push({ ...value.links[0].postings[0] }) },
  ]
  for (const edit of variants) { const value = saved(); edit(value); assert.throws(() => parseIntakeStore(JSON.stringify(value))) }
  assert.deepEqual(store, saved())
})

test('failed saves, corrupt storage and changes in another tab cannot overwrite previous links', () => {
  const storage = memory()
  writeIntakeStore(storage, saved(), emptyIntakeStore())
  const before = storage.values.get(INTAKE_STORAGE_KEY)
  assert.throws(() => writeIntakeStore({ ...storage, setItem: () => { throw new Error('quota') } }, emptyIntakeStore(), saved()), /Previous links and the roster are unchanged/)
  assert.equal(storage.values.get(INTAKE_STORAGE_KEY), before)
  assert.throws(() => writeIntakeStore(storage, emptyIntakeStore(), emptyIntakeStore()), /changed.*Re-import/)
  assert.equal(storage.values.get(INTAKE_STORAGE_KEY), before)
  storage.values.set(INTAKE_STORAGE_KEY, 'broken')
  assert.throws(() => readIntakeStore(storage), /not valid JSON/)
  assert.throws(() => writeIntakeStore(storage, emptyIntakeStore(), emptyIntakeStore()), /could not be read.*Re-import/)
  assert.equal(storage.values.get(INTAKE_STORAGE_KEY), 'broken')
  writeIntakeStore(storage, emptyIntakeStore(), emptyIntakeStore(), true)
  assert.deepEqual(readIntakeStore(storage), emptyIntakeStore())
})

test('projection API receives the original import and independent intake store', async (t) => {
  const workbook = { residents: [], intake_links: [] } as unknown as Workbook
  t.mock.method(globalThis, 'fetch', async (url: string, init: RequestInit) => {
    assert.equal(url, '/api/intake-links')
    assert.deepEqual(JSON.parse(String(init.body)), { workbook, store: saved() })
    return Response.json(workbook)
  })
  assert.deepEqual(await applyIntakeLinks(workbook, saved()), workbook)
  t.mock.method(globalThis, 'fetch', async () => Response.json({ detail: 'Re-import the workbook.' }, { status: 422 }))
  await assert.rejects(applyIntakeLinks(workbook, saved()), /Re-import/)
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch') })
  await assert.rejects(applyIntakeLinks(workbook, saved()), /Check the connection.*previous roster is unchanged/)
})

test('Incoming R1 uses a compact disclosure with explicit linking and reviewable saved states', async () => {
  const vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  try {
    const { default: IncomingIntake } = await vite.ssrLoadModule('/src/components/IncomingIntake.tsx')
    const workbook = { target_year: 2027, residents: [], issues: [], intake_links: [{ ...saved().links[0], status: 'needs_review', message: 'Resident identity changed.' }] }
    const props = { workbook, store: saved(), busy: false, storageError: '', onSave: async () => {}, onIssues: () => {} }
    const html = renderToStaticMarkup(createElement(IncomingIntake, props))
    assert.match(html, /<details class="incoming-intake"/)
    assert.match(html, /Named incoming resident<select/)
    assert.match(html, /Intake slot<select/)
    assert.match(html, /Confirm link/)
    assert.match(html, /Needs review.*Resident identity changed/)
    assert.match(html, /aria-label="Remove link for Incoming Example"/)
    assert.match(html, /Export intake links/)
    const corrupt = renderToStaticMarkup(createElement(IncomingIntake, { ...props, storageError: 'Invalid JSON.' }))
    assert.match(corrupt, /Discard unreadable intake links and start new/)
    assert.match(corrupt, /Confirm link<\/button>/)
    assert.match(corrupt, /<select disabled=""/)
  } finally { await vite.close() }
})
