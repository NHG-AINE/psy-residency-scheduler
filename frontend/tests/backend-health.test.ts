import assert from 'node:assert/strict'
import test from 'node:test'
import { checkBackendHealth } from '../src/lib/backend-health.ts'

test('accepts the backend health contract through the relative API path', async (t) => {
  t.mock.method(globalThis, 'fetch', async (url: string) => {
    assert.equal(url, '/api/health')
    return Response.json({ status: 'ok' })
  })
  await assert.doesNotReject(checkBackendHealth())
})

test('does not treat an HTTP failure as a connected backend', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 503 }))
  await assert.rejects(checkBackendHealth(), /HTTP 503/)
})

test('rejects a frontend HTML fallback instead of showing a false connection', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<!doctype html><html></html>'))
  await assert.rejects(checkBackendHealth(), /valid JSON/)
})

test('does not accept an unhealthy or unrelated JSON response', async (t) => {
  for (const body of [null, { status: 'error' }, { message: 'ok' }]) {
    t.mock.method(globalThis, 'fetch', async () => Response.json(body))
    await assert.rejects(checkBackendHealth(), /status ok/)
  }
})
