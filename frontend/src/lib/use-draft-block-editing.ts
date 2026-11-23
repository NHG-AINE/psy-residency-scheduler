import { useLayoutEffect, useRef, useState } from 'react'
import { draftSwapOutcome, validateDraftChange } from './draft-schedule'
import type { DraftChange, DraftChangeIssue, DraftChangeResult, DraftSchedule } from './draft-schedule'
import type { ReviewStore } from './history-review'
import { sameSource } from './workbook'
import type { Source, Workbook } from './workbook'

export type DraftBlock = { source: Source; name: string; label: string; start: string; months: string[]; id: string; anchor: HTMLButtonElement }
export type DraftCell = Pick<DraftBlock, 'source' | 'start' | 'months'> & { leave?: boolean }
type ReleasedSwap = { from: DraftBlock; focus: DraftBlock; anchor: HTMLElement; keyboard: boolean }

function sameBlock(a: DraftCell | null | undefined, b: DraftCell | null | undefined) {
  return !!a && !!b && sameSource(a.source, b.source) && a.start === b.start
}

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
  const [move, setMove] = useState<{ from: DraftBlock; keyboard: boolean } | null>(null)
  const moving = useRef(move)
  const target = useRef<DraftCell | null>(null)
  const [destination, setDestination] = useState<DraftCell | null>(null)
  const [released, setReleased] = useState<ReleasedSwap | null>(null)
  const [preview, setPreview] = useState<DraftChangeResult | null>(null)
  const [checking, setChecking] = useState(false)
  const [announcement, announce] = useState('')
  const [context, setContext] = useState({ workbook, store, draft, disabled })
  const active = useRef<{ controller: AbortController; checked?: DraftChangeResult; released?: ReleasedSwap } | null>(null)
  const cache = useRef(new Map<string, DraftChangeResult>())
  if (context.workbook !== workbook || context.store !== store || context.draft !== draft || context.disabled !== disabled) {
    if (move || released) announce('')
    setContext({ workbook, store, draft, disabled })
    setEditor(null); setMove(null); setDestination(null); setReleased(null); setPreview(null); setChecking(false)
  }

  function clearPreview() {
    active.current?.controller.abort()
    active.current = null
    setPreview(null); setChecking(false)
  }

  function stopMove() {
    moving.current = null; target.current = null; setMove(null); setDestination(null); setReleased(null)
  }

  useLayoutEffect(() => {
    active.current = null; moving.current = null; target.current = null
    cache.current.clear()
    return () => active.current?.controller.abort()
  }, [workbook, store, draft, disabled])

  function openEditor(block: DraftBlock) {
    if (disabled) return
    stopMove(); clearPreview(); setEditor(block)
  }

  function closeEditor() {
    clearPreview(); setEditor(null)
    if (editor) requestAnimationFrame(() => focusBlock(editor))
  }

  function startMove(from: DraftBlock, keyboard: boolean) {
    if (disabled) return
    cancelMove()
    const next = { from, keyboard }
    moving.current = next; setMove(next)
    if (keyboard) announce(`Picked up ${from.label}. Use the arrow keys to choose a block, Enter to swap, or Escape to cancel.`)
  }

  function cancelMove() {
    stopMove(); clearPreview()
  }

  function check(change: DraftChange, affected: DraftCell[], debounce = 0) {
    clearPreview()
    if (!draft || disabled) return
    const key = JSON.stringify(change)
    const cached = cache.current.get(key)
    const operation: NonNullable<typeof active.current> = { controller: new AbortController(), checked: cached }
    active.current = operation
    if (cached) {
      setPreview(cached)
      if (change.kind === 'swap') announce(cached.issues.map((issue) => issue.message).join(' ') || 'Swap available.')
      return
    }
    setChecking(true)
    if (change.kind === 'swap') announce('Checking the swap.')
    const { signal } = operation.controller
    void (async () => {
      if (debounce) await new Promise((resolve) => window.setTimeout(resolve, debounce))
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
      const outcome = draftSwapOutcome(result)
      if (operation.released && outcome === 'clean' && apply(operation.released.focus)) return
      setPreview(result); setChecking(false)
      if (change.kind === 'swap') {
        const reason = result.issues.map((issue) => issue.message).join(' ')
        announce(operation.released && outcome === 'warning' ? 'Review the swap warning before applying.'
          : reason || (outcome === 'clean' && !operation.released ? 'Swap available.' : 'Could not apply this swap. Try again.'))
      }
    })()
  }

  function selectDestination(next: DraftCell) {
    const held = moving.current
    if (!held || sameBlock(target.current, next)) return
    target.current = next; setDestination(next)
    const { from, keyboard } = held
    if (sameBlock(from, next)) { clearPreview(); announce('Original position.'); return }
    const message = !sameSource(from.source, next.source) ? `Choose a block in ${from.name}’s row.`
      : next.leave ? 'This period is recorded leave. A posting cannot be assigned during leave.'
        : !next.months.length ? 'Only generated posting blocks can be swapped.'
        : from.months.length !== next.months.length ? `Only equal-length blocks can swap. These blocks span ${from.months.length} and ${next.months.length} training months.` : ''
    if (message) {
      clearPreview()
      setPreview({ draft: null, issues: [{ severity: 'hard', code: 'invalid_destination', message,
        affected: [from, next].map(({ source, start }) => ({ source, month: start })) }] })
      announce(message)
      return
    }
    check({ kind: 'swap', resident: from.source, start: from.start, destination: next.start }, [from, next], keyboard ? 0 : 120)
  }

  function apply(block: DraftBlock) {
    const operation = active.current
    const checked = operation?.checked
    if (!draft || !checked?.draft || checked.issues.some((issue) => issue.severity === 'hard')) return false
    if (!applyChange(draft, checked.draft)) return false
    cancelMove(); setEditor(null)
    announce(`${block.name}’s draft updated.${checked.issues.length ? ` ${checked.issues.map((issue) => issue.message).join(' ')}` : ''}`)
    requestAnimationFrame(() => focusBlock(block))
    return true
  }

  function finishDrag() {
    if (!moving.current || moving.current.keyboard) return
    cancelMove()
  }

  function drop(next: DraftCell, anchor: HTMLElement, focusAfterSwap?: DraftBlock) {
    const held = moving.current
    if (!held) return
    const { from, keyboard } = held
    if (sameBlock(from, next)) { cancelMove(); return }
    selectDestination(next)
    const operation = active.current
    const focus = focusAfterSwap ?? from
    if (operation?.checked && draftSwapOutcome(operation.checked) === 'clean' && apply(focus)) return
    const swap = { from, focus, anchor, keyboard }
    if (operation) operation.released = swap
    moving.current = null; setMove(null); setReleased(swap)
  }

  function dismissDrop(restoreFocus = true) {
    if (!released) return
    cancelMove(); announce(checking ? 'Swap cancelled.' : '')
    if (restoreFocus) focusBlock(released.from)
  }

  function confirmDrop() {
    if (released) apply(released.focus)
  }

  function endKeyboardMove(restoreFocus: boolean) {
    const from = moving.current?.from
    cancelMove(); announce('Swap cancelled.')
    if (restoreFocus && from) focusBlock(from)
  }

  return { editor, openEditor, closeEditor, move, moving, destination, released, preview, checking, announcement,
    clearPreview, check, startMove, selectDestination, apply, drop, dismissDrop, confirmDrop, finishDrag, endKeyboardMove }
}
