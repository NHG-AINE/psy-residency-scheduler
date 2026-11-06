import { useEffect, useState } from 'react'

export default function DraftTimer({ startedAt, elapsedSeconds }: { startedAt: number | null; elapsedSeconds: number | null }) {
  const [now, setNow] = useState(() => performance.now())
  useEffect(() => {
    if (startedAt === null) return
    const timer = window.setInterval(() => setNow(performance.now()), 1000)
    return () => window.clearInterval(timer)
  }, [startedAt])
  const seconds = startedAt === null ? elapsedSeconds : Math.max(0, Math.floor((now - startedAt) / 1000))
  if (seconds === null) return null
  const duration = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
  return <span className="draft-timer" role="timer" aria-live="off">{startedAt === null ? `Generated in ${duration}` : `${duration} elapsed`}</span>
}
