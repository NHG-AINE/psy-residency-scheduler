import * as Collapsible from '@radix-ui/react-collapsible'
import { useEffect, useState } from 'react'
import { checkBackendHealth } from '../lib/backend-health'

type Connection = 'checking' | 'ready' | 'unavailable'

const labels: Record<Connection, string> = {
  checking: 'Checking backend',
  ready: 'Backend connected',
  unavailable: 'Backend unavailable',
}

export default function ConnectionStatus() {
  const [connection, setConnection] = useState<Connection>('checking')
  const [detail, setDetail] = useState('Waiting for the health check.')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    void checkBackendHealth(controller.signal).then(
      () => {
        if (!controller.signal.aborted) {
          setConnection('ready')
          setDetail('The backend health endpoint returned status ok.')
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setConnection('unavailable')
          setDetail(error instanceof Error ? error.message : 'The request failed.')
        }
      },
    )
    return () => controller.abort()
  }, [attempt])

  return (
    <Collapsible.Root className="connection-panel">
      <div className="connection-summary">
        <div className="connection-copy">
          <p className={`connection-label ${connection}`} role="status" aria-live="polite">
            <span className="status-dot" aria-hidden="true" />
            {labels[connection]}
          </p>
          <p className="connection-help">
            {connection === 'ready'
              ? 'The frontend can reach the API.'
              : connection === 'checking'
                ? 'Contacting the API…'
                : 'Start the backend, then check the connection again.'}
          </p>
        </div>
        <button
          className="button"
          type="button"
          disabled={connection === 'checking'}
          onClick={() => {
            setConnection('checking')
            setDetail('Waiting for the health check.')
            setAttempt((value) => value + 1)
          }}
        >
          {connection === 'checking' ? 'Checking…' : 'Check connection'}
        </button>
      </div>

      <Collapsible.Trigger className="details-trigger">
        Connection details
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 9 5 5 5-5" /></svg>
      </Collapsible.Trigger>
      <Collapsible.Content className="connection-details">
        <p>{detail}</p>
        <p>The frontend checks <code>/api/health</code> through the development proxy.</p>
      </Collapsible.Content>
    </Collapsible.Root>
  )
}
