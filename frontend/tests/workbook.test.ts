import assert from 'node:assert/strict'
import test from 'node:test'
import { importWorkbook, workbookError } from '../src/lib/workbook.ts'

test('validates one nonempty XLSX at the exact 10 MiB boundary', () => {
  assert.match(workbookError([]), /one workbook/)
  assert.match(workbookError([{ name: 'a.xlsx', size: 1 }, { name: 'b.xlsx', size: 1 }]), /one workbook/)
  assert.match(workbookError([{ name: 'a.xls', size: 1 }]), /\.xlsx/)
  assert.match(workbookError([{ name: 'a.xlsx', size: 0 }]), /empty/)
  assert.match(workbookError([{ name: 'a.xlsx', size: 10 * 1024 * 1024 + 1 }]), /10 MB/)
  assert.equal(workbookError([{ name: 'a.XLSX', size: 10 * 1024 * 1024 }]), '')
})

test('uploads the file and target year as multipart without overriding its boundary', async (t) => {
  const file = new File(['workbook'], 'programme.xlsx')
  const result = { target_year: 2027, target_sheet: 'Jul 27 - Jun 28', residents: [], available_years: [], months: [], histories: [], requests: [], warnings: [], postings: { core: [], rows: [] } }
  t.mock.method(globalThis, 'fetch', async (url: string, init: RequestInit) => {
    assert.equal(url, '/api/import')
    assert.equal(init.method, 'POST')
    assert.equal(init.headers, undefined)
    assert.ok(init.signal instanceof AbortSignal)
    assert.equal(init.signal.aborted, false)
    const body = init.body as FormData
    assert.equal((body.get('file') as File).name, file.name)
    assert.equal(body.get('target_year'), '2027')
    return Response.json(result)
  })
  assert.deepEqual(await importWorkbook(file, 2027), result)
})

test('reports server validation, unreachable backend and non-JSON responses', async (t) => {
  const file = new File(['workbook'], 'programme.xlsx')
  t.mock.method(globalThis, 'fetch', async () => Response.json({ detail: 'Missing required worksheet.' }, { status: 400 }))
  await assert.rejects(importWorkbook(file, 2027), /Missing required worksheet/)
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch') })
  await assert.rejects(importWorkbook(file, 2027), /Could not reach/)
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>Vite fallback</html>'))
  await assert.rejects(importWorkbook(file, 2027), /valid JSON/)
  t.mock.method(globalThis, 'fetch', async () => Response.json({ status: 'ok' }))
  await assert.rejects(importWorkbook(file, 2027), /unexpected workbook/)
  t.mock.method(globalThis, 'fetch', async () => Response.json({ residents: [], available_years: [] }))
  await assert.rejects(importWorkbook(file, 2027), /unexpected workbook/)
  t.mock.method(globalThis, 'fetch', async () => { throw new DOMException('timeout', 'TimeoutError') })
  await assert.rejects(importWorkbook(file, 2027), /timed out/)
})
