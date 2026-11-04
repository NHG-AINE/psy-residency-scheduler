import { useEffect, useRef, useState } from 'react'
import { generateDraft } from './draft-schedule'
import type { DraftSchedule } from './draft-schedule'
import { readReviewStore, REVIEW_CHANGED, STORAGE_KEY } from './history-review'
import type { Workbook } from './workbook'

export function useDraftSchedule(workbook: Workbook | null, importing: boolean) {
  const [result, setResult] = useState<{ workbook: Workbook; data: DraftSchedule } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const active = useRef<AbortController | null>(null)
  function discard() {
    active.current?.abort(); active.current = null
    setResult(null); setBusy(false); setError('')
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
  async function generate() {
    if (!workbook || importing || active.current) return
    const controller = new AbortController()
    active.current = controller
    setBusy(true); setError('')
    try {
      const saved = readReviewStore(window.localStorage)
      if (saved.error) throw new Error(saved.error)
      const data = await generateDraft(workbook, saved.store, controller.signal)
      if (!controller.signal.aborted) setResult({ workbook, data })
    } catch (problem) {
      if (!controller.signal.aborted) setError(problem instanceof Error ? problem.message : 'Draft generation failed. Retry.')
    } finally {
      if (active.current === controller) { active.current = null; setBusy(false) }
    }
  }
  return { draft: !importing && result?.workbook === workbook ? result.data : null, busy, error, generate, discard }
}
export type DraftState = ReturnType<typeof useDraftSchedule>
