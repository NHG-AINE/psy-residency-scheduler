import { useEffect, useRef, useState } from 'react'
import { generateDraft } from './draft-schedule'
import type { DraftSchedule } from './draft-schedule'
import { readReviewStore, REVIEW_CHANGED, STORAGE_KEY } from './history-review'
import type { Workbook } from './workbook'

export function useDraftSchedule(workbook: Workbook | null, importing: boolean) {
  const [results, setResults] = useState<Record<number, { data: DraftSchedule; elapsedSeconds: number }>>({})
  const [busy, setBusy] = useState(false)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [error, setError] = useState('')
  const active = useRef<AbortController | null>(null)
  function cancelGeneration() {
    active.current?.abort(); active.current = null
    setBusy(false); setStartedAt(null); setError('')
  }
  function reset() {
    cancelGeneration()
    setResults({})
  }
  function discard() {
    cancelGeneration()
    if (workbook) setResults((previous) => {
      const next = { ...previous }
      delete next[workbook.target_year]
      return next
    })
  }
  useEffect(() => {
    const changed = (event: Event) => {
      if (!(event instanceof StorageEvent) || event.key === STORAGE_KEY || event.key === null) reset()
    }
    window.addEventListener('storage', changed)
    window.addEventListener(REVIEW_CHANGED, changed)
    return () => {
      active.current?.abort(); active.current = null
      window.removeEventListener('storage', changed)
      window.removeEventListener(REVIEW_CHANGED, changed)
    }
  }, [])
  async function generate() {
    if (!workbook || importing || active.current) return
    const controller = new AbortController()
    active.current = controller
    const start = performance.now()
    setStartedAt(start)
    setBusy(true); setError('')
    try {
      const saved = readReviewStore(window.localStorage)
      if (saved.error) throw new Error(saved.error)
      const data = await generateDraft(workbook, saved.store, controller.signal)
      if (!controller.signal.aborted) {
        const elapsedSeconds = Math.floor((performance.now() - start) / 1000)
        setResults((previous) => ({ ...previous, [workbook.target_year]: { data, elapsedSeconds } }))
      }
    } catch (problem) {
      if (!controller.signal.aborted) setError(problem instanceof Error ? problem.message : 'Draft generation failed. Retry.')
    } finally {
      if (active.current === controller) { active.current = null; setBusy(false); setStartedAt(null) }
    }
  }
  const result = !importing && workbook ? results[workbook.target_year] : undefined
  return { draft: result?.data ?? null, busy, error, generate, discard, reset, cancelGeneration, startedAt,
    elapsedSeconds: result && ['optimal', 'feasible'].includes(result.data.status) ? result.elapsedSeconds : null }
}
export type DraftState = ReturnType<typeof useDraftSchedule>
