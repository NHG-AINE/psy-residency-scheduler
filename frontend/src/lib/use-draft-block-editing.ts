import { useLayoutEffect, useRef, useState } from 'react'
import { validateDraftChange } from './draft-schedule'
import type { DraftChange, DraftChangeIssue, DraftChangeResult, DraftSchedule } from './draft-schedule'
import type { ReviewStore } from './history-review'
import { sameSource } from './workbook'
import type { Source, Workbook } from './workbook'

export type DraftBlock = { source: Source; name: string; label: string; start: string; months: string[]; id: string; anchor: HTMLButtonElement }
export type DraftCell = Pick<DraftBlock, 'source' | 'start' | 'months'> & { leave?: boolean }
export function focusBlock(block: DraftBlock) {
  const candidate = block.anchor.isConnected ? block.anchor : document.getElementById(block.id)
  const target = candidate instanceof HTMLButtonElement && !candidate.disabled ? candidate : document.getElementById('resident-search')
  target?.focus({ preventScroll: true })
}

export function issuesForCell(issues: DraftChangeIssue[], source: Source, months: string[]) {
  return issues.filter((issue) => issue.affected.some((cell) => sameSource(cell.source, source) && months.includes(cell.month)))
}

export function useDraftBlockEditing(workbook: Workbook, store: ReviewStore, draft: DraftSchedule | null, disabled: boolean,
  applyChange: (previous: DraftSchedule, next: DraftSchedule) => boolean) {
  const [editor, setEditor] = useState<DraftBlock | null>(null)
  const [preview, setPreview] = useState<DraftChangeResult | null>(null)
  const [checking, setChecking] = useState(false)
  const [announcement, announce] = useState('')
  const [context, setContext] = useState({ workbook, store, draft, disabled })
  const active = useRef<{ controller: AbortController; checked?: DraftChangeResult } | null>(null)
  const cache = useRef(new Map<string, DraftChangeResult>())
  if (context.workbook !== workbook || context.store !== store || context.draft !== draft || context.disabled !== disabled) {
    setContext({ workbook, store, draft, disabled })
    setEditor(null); setPreview(null); setChecking(false)
  }

  function clearPreview() {
    active.current?.controller.abort()
    active.current = null
    setPreview(null); setChecking(false)
  }

  useLayoutEffect(() => {
    active.current = null
    cache.current.clear()
    return () => active.current?.controller.abort()
  }, [workbook, store, draft, disabled])

  function openEditor(block: DraftBlock) {
    if (disabled) return
    clearPreview(); setEditor(block)
  }

  function closeEditor() {
    clearPreview(); setEditor(null)
    if (editor) requestAnimationFrame(() => focusBlock(editor))
  }

  function check(change: DraftChange, affected: DraftCell[]) {
    clearPreview()
    if (!draft || disabled) return
    const key = JSON.stringify(change)
    const cached = cache.current.get(key)
    const operation: NonNullable<typeof active.current> = { controller: new AbortController(), checked: cached }
    active.current = operation
    if (cached) {
      setPreview(cached)
      return
    }
    setChecking(true)
    const { signal } = operation.controller
    void (async () => {
      if (signal.aborted) return
      let result: DraftChangeResult
      try {
        result = await validateDraftChange(workbook, store, draft, change, signal)
      } catch (error) {
        result = { draft: null, issues: [{ severity: 'hard', code: 'validation_error',
          message: error instanceof Error && !['AbortError', 'TimeoutError', 'TypeError'].includes(error.name)
            ? error.message : 'Could not check this change. Try again.',
          affected: affected.map(({ start, source }) => ({ month: start, source })) }] }
      }
      if (signal.aborted || active.current !== operation) return
      operation.checked = result
      if (!result.issues.some((issue) => issue.code === 'validation_error')) {
        const oldest = cache.current.keys().next().value
        if (cache.current.size === 12 && oldest !== undefined) cache.current.delete(oldest)
        cache.current.set(key, result)
      }
      setPreview(result); setChecking(false)
    })()
  }


  function apply(block: DraftBlock) {
    const operation = active.current
    const checked = operation?.checked
    if (!draft || !checked?.draft || checked.issues.some((issue) => issue.severity === 'hard')) return false
    if (!applyChange(draft, checked.draft)) return false
    clearPreview(); setEditor(null)
    announce(`${block.name}’s draft updated.${checked.issues.length ? ` ${checked.issues.map((issue) => issue.message).join(' ')}` : ''}`)
    requestAnimationFrame(() => focusBlock(block))
    return true
  }

  return { editor, openEditor, closeEditor, preview, checking, announcement, clearPreview, check, apply }
}
