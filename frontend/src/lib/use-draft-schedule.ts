import { useEffect, useRef, useState } from 'react'
import { canGenerateDraft, generateDraft } from './draft-schedule'
import type { DraftSchedule } from './draft-schedule'
import { readReviewStore, REVIEW_CHANGED, STORAGE_KEY } from './history-review'
import type { Workbook } from './workbook'

export function useDraftSchedule(workbook: Workbook | null, importing: boolean, selectedYear: number) {
  const [result, setResult] = useState<{ year: number; data: DraftSchedule; elapsedSeconds: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [originYear, setOriginYear] = useState<number | null>(null)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [error, setError] = useState('')
  const active = useRef<AbortController | null>(null)
  function cancelGeneration() {
    active.current?.abort(); active.current = null
    setBusy(false); setStartedAt(null); setError('')
  }
  function discard() {
    cancelGeneration()
    setResult(null)
  }
  useEffect(() => {
    const changed = (event: Event) => {
      if (!(event instanceof StorageEvent) || event.key === STORAGE_KEY || event.key === null) discard()
    }
    window.addEventListener('storage', changed)
    window.addEventListener(REVIEW_CHANGED, changed)
    return () => {
      active.current?.abort(); active.current = null
      window.removeEventListener('storage', changed)
      window.removeEventListener(REVIEW_CHANGED, changed)
    }
  }, [])
  const canGenerate = canGenerateDraft(workbook, selectedYear, importing)
  async function generate() {
    if (!workbook || !canGenerate || importing || active.current) return
    const controller = new AbortController()
    active.current = controller
    const start = performance.now()
    setOriginYear(workbook.target_year)
    setStartedAt(start)
    setBusy(true); setError('')
    try {
      const saved = readReviewStore(window.localStorage)
      if (saved.error) throw new Error(saved.error)
      const data = await generateDraft(workbook, saved.store, controller.signal)
      if (!controller.signal.aborted) {
        const elapsedSeconds = Math.floor((performance.now() - start) / 1000)
        setResult({ year: workbook.target_year, data, elapsedSeconds })
      }
    } catch (problem) {
      if (!controller.signal.aborted) setError(problem instanceof Error ? problem.message : 'Draft generation failed. Retry.')
    } finally {
      if (active.current === controller) { active.current = null; setBusy(false); setStartedAt(null) }
    }
  }
  const visible = !importing && canGenerate && result?.year === workbook?.target_year ? result : null
  const onOriginYear = canGenerate && originYear === selectedYear
  return { draft: visible?.data ?? null, busy: busy && onOriginYear, error: onOriginYear ? error : '', canGenerate, generate, discard, cancelGeneration, startedAt: onOriginYear ? startedAt : null,
    elapsedSeconds: visible && ['optimal', 'feasible'].includes(visible.data.status) ? visible.elapsedSeconds : null }
}
export type DraftState = ReturnType<typeof useDraftSchedule>
