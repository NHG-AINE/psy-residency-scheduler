import { useCallback, useEffect, useRef, useState } from 'react'
import { canGenerateDraft, cancelDraft, generateDraft, settleDraftAttempt, startDraft } from './draft-schedule'
import type { DraftResult } from './draft-schedule'
import type { SavedDraft } from './workbook-session'
import { readReviewStore, reviewSignature, REVIEW_CHANGED, STORAGE_KEY } from './history-review'
import type { Workbook } from './workbook'

export function useDraftSchedule(workbook: Workbook | null, importing: boolean, selectedYear: number | undefined) {
  const [result, setResult] = useState<DraftResult>({ saved: null, failure: null })
  const [searchSeconds, setSearchSeconds] = useState(120)
  const [busy, setBusy] = useState(false)
  const [originYear, setOriginYear] = useState<number | null>(null)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const resultRef = useRef(result)
  const updateResult = useCallback((value: DraftResult) => { resultRef.current = value; setResult(value) }, [])
  const [cancelling, setCancelling] = useState(false)
  const active = useRef<{ token: Promise<string>; controller: AbortController; cancelled: boolean; invalidated: boolean; reviewSignature: string | null } | null>(null)
  const cancelGeneration = useCallback(async () => {
    const operation = active.current
    if (!operation || operation.cancelled) return
    operation.cancelled = true
    setCancelling(true); setError('')
    try {
      const token = await operation.token
      await cancelDraft(token)
      operation.controller.abort()
    } catch {
      if (active.current === operation && !operation.invalidated) {
        operation.cancelled = false
        setCancelling(false)
        setError('Could not cancel draft generation. Check the connection and retry.')
      }
    }
  }, [])
  const discard = useCallback((reason = '') => {
    if (active.current) {
      active.current.invalidated = true
      active.current.controller.abort()
    }
    void cancelGeneration()
    updateResult({ saved: null, failure: null }); setOriginYear(null); setError(''); setNotice(reason)
  }, [cancelGeneration, updateResult])
  useEffect(() => {
    const changed = (event: Event) => {
      if (event instanceof StorageEvent && event.key !== STORAGE_KEY && event.key !== null) return
      const prior = active.current?.reviewSignature ?? resultRef.current.saved?.reviewSignature
      if (prior === undefined || prior === null) return
      try {
        const saved = readReviewStore(window.localStorage)
        if (saved.error || reviewSignature(saved.store) !== prior) discard('Review decisions changed. The previous draft was cleared; generate a new draft.')
      } catch { discard('Review decisions could not be checked. The previous draft was cleared; check browser storage before generating again.') }
    }
    window.addEventListener('storage', changed)
    window.addEventListener(REVIEW_CHANGED, changed)
    return () => {
      void cancelGeneration()
      window.removeEventListener('storage', changed)
      window.removeEventListener(REVIEW_CHANGED, changed)
    }
  }, [cancelGeneration, discard])
  const restore = useCallback((saved: SavedDraft) => {
    try {
      const reviews = readReviewStore(window.localStorage)
      if (reviews.error || reviewSignature(reviews.store) !== saved.reviewSignature) {
        setNotice('Review decisions changed or could not be checked. The saved workbook was restored without its draft; generate a new draft.')
        return
      }
      updateResult({ saved, failure: null }); setOriginYear(saved.year)
    } catch { setNotice('Review decisions could not be checked. The saved workbook was restored without its draft.') }
  }, [updateResult])
  const getSavedResult = useCallback(() => resultRef.current.saved, [])
  const canGenerate = canGenerateDraft(workbook, selectedYear, importing)
  async function generate() {
    if (!workbook || !canGenerate || importing || active.current) return
    const operation = { token: startDraft(), controller: new AbortController(), cancelled: false, invalidated: false, reviewSignature: null as string | null }
    active.current = operation
    const start = performance.now()
    setOriginYear(workbook.target_year)
    setStartedAt(start)
    setBusy(true); updateResult({ saved: resultRef.current.saved, failure: null }); setError(''); setNotice('')
    try {
      const saved = readReviewStore(window.localStorage)
      if (saved.error) throw new Error(saved.error)
      operation.reviewSignature = reviewSignature(saved.store)
      const token = await operation.token
      if (operation.cancelled || operation.invalidated) return
      const data = await generateDraft(workbook, saved.store, operation.controller.signal, token, searchSeconds)
      const elapsedSeconds = Math.floor((performance.now() - start) / 1000)
      updateResult(settleDraftAttempt(resultRef.current, { year: workbook.target_year, data, elapsedSeconds, reviewSignature: operation.reviewSignature }, operation))
    } catch (problem) {
      if (!operation.cancelled && !operation.invalidated) setError(problem instanceof Error ? problem.message : 'Draft generation failed. Retry.')
    } finally {
      if (active.current === operation) { active.current = null; setBusy(false); setCancelling(false); setStartedAt(null) }
      void operation.token.then(cancelDraft).catch(() => {})
    }
  }
  const visible = canGenerate && result.saved?.year === workbook?.target_year ? result.saved : null
  const onOriginYear = canGenerate && originYear === selectedYear
  return { savedResult: result.saved, getSavedResult, restore, notice, searchSeconds, setSearchSeconds, draft: visible?.data ?? null, busy: busy && onOriginYear, pending: busy, cancelling: cancelling && onOriginYear, error: onOriginYear ? error : '', failedAttempt: onOriginYear ? result.failure : null, canGenerate, generate, discard, cancelGeneration, startedAt: onOriginYear ? startedAt : null,
    elapsedSeconds: visible?.elapsedSeconds ?? null }
}
export type DraftState = ReturnType<typeof useDraftSchedule>
