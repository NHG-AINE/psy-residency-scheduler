export async function checkBackendHealth(signal?: AbortSignal): Promise<void> {
  const timeout = AbortSignal.timeout(5000)
  const response = await fetch('/api/health', {
    headers: { Accept: 'application/json' },
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
  })

  if (!response.ok) {
    throw new Error(`The backend health check returned HTTP ${response.status}.`)
  }

  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new Error('The health endpoint did not return valid JSON.')
  }

  if (typeof body !== 'object' || body === null || !('status' in body) || body.status !== 'ok') {
    throw new Error('The health endpoint did not report status ok.')
  }
}
