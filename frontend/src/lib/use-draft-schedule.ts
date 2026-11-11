import { useEffect, useRef, useState } from 'react'
import { canGenerateDraft, cancelDraft, generateDraft, startDraft } from './draft-schedule'
import type { DraftSchedule } from './draft-schedule'
import { readReviewStore, REVIEW_CHANGED, STORAGE_KEY } from './history-review'
import type { Workbook } from './workbook'

export function useDraftSchedule(workbook: Workbook | null, importing: boolean, selectedYear: number) {
  const [result, setResult] = useState<{ year: number; data: DraftSchedule; elapsedSeconds: number } | null>(null)
  const [searchSeconds, setSearchSeconds] = useState(120)
  const [busy, setBusy] = useState(false)
  const [originYear, setOriginYear] = useState<number | null>(null)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [cancelling, setCancelling] = useState(false)
  const active = useRef<{ token: Promise<string>; cancelled: boolean; invalidated: boolean } | null>(null)
  async function cancelGeneration() {
    const operation = active.current
    if (!operation || operation.cancelled) return
    operation.cancelled = true
    setCancelling(true); setError('')
    try {
      const token = await operation.token
      await cancelDraft(token)
    } catch {
      if (active.current === operation) {
        operation.cancelled = false
        setCancelling(false)
        setError('Could not cancel draft generation. Check the connection and retry.')
      }
    }
  }
  function discard() {
    if (active.current) active.current.invalidated = true
    void cancelGeneration()
    setResult(null); setOriginYear(null)
  }
  useEffect(() => {
    const changed = (event: Event) => {
      if (!(event instanceof StorageEvent) || event.key === STORAGE_KEY || event.key === null) discard()
    }
    window.addEventListener('storage', changed)
    window.addEventListener(REVIEW_CHANGED, changed)
    return () => {
      void cancelGeneration()
      window.removeEventListener('storage', changed)
      window.removeEventListener(REVIEW_CHANGED, changed)
    }
  }, [])
  const canGenerate = canGenerateDraft(workbook, selectedYear, importing)
  async function generate() {
    if (!workbook || !canGenerate || importing || active.current) return
    const controller = new AbortController()
    const operation = { token: startDraft(), cancelled: false, invalidated: false }
    active.current = operation
    const start = performance.now()
    setOriginYear(workbook.target_year)
    setStartedAt(start)
    setBusy(true); setError('')
    try {
      const saved = readReviewStore(window.localStorage)
      if (saved.error) throw new Error(saved.error)
      const token = await operation.token
      if (operation.cancelled) return
      const data = await generateDraft(workbook, saved.store, controller.signal, token, searchSeconds)
      if (!operation.cancelled && !operation.invalidated) {
        const elapsedSeconds = Math.floor((performance.now() - start) / 1000)
        setResult({ year: workbook.target_year, data, elapsedSeconds })
      }
    } catch (problem) {
      if (!operation.cancelled && !operation.invalidated) setError(problem instanceof Error ? problem.message : 'Draft generation failed. Retry.')
    } finally {
      if (active.current === operation) { active.current = null; setBusy(false); setCancelling(false); setStartedAt(null) }
      void operation.token.then(cancelDraft).catch(() => {})
    }
  }
  const visible = !importing && canGenerate && result?.year === workbook?.target_year ? result : null
  const onOriginYear = canGenerate && originYear === selectedYear
  return { searchSeconds, setSearchSeconds, draft: visible?.data ?? null, busy: busy && onOriginYear, pending: busy, cancelling: cancelling && onOriginYear, error: onOriginYear ? error : '', canGenerate, generate, discard, cancelGeneration, startedAt: onOriginYear ? startedAt : null,
    elapsedSeconds: visible && ['optimal', 'feasible'].includes(visible.data.status) ? visible.elapsedSeconds : null }
}
export type DraftState = ReturnType<typeof useDraftSchedule>
