import { useEffect, useState } from 'react'
import DraftTimingDetails from './DraftTimingDetails'
import type { DraftSchedule } from '../lib/draft-schedule'

export default function DraftTimer({ startedAt, elapsedSeconds, draft }: { startedAt: number | null; elapsedSeconds: number | null; draft?: DraftSchedule | null }) {
  const [now, setNow] = useState(() => performance.now())
  useEffect(() => {
    if (startedAt === null) return
    const timer = window.setInterval(() => setNow(performance.now()), 1000)
    return () => window.clearInterval(timer)
  }, [startedAt])
  const seconds = startedAt === null ? elapsedSeconds : Math.max(0, Math.floor((now - startedAt) / 1000))
  if (seconds === null) return null
  const duration = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
  if (startedAt === null && draft?.optimisation_stages?.length) {
    return <DraftTimingDetails draft={draft} elapsedSeconds={seconds} duration={duration} />
  }
  return <span className="draft-timer" role="timer" aria-live="off">{startedAt === null ? `Generated in ${duration}` : `${duration} elapsed`}</span>
}
