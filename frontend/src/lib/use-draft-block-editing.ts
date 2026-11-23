import { useLayoutEffect, useRef, useState } from 'react'
import { prepareDraftEdit } from './draft-edit-history'
import { draftInsertion, draftSwapLayout, draftSwapOutcome, monthRanges, validateDraftChange } from './draft-schedule'
import type { DraftChange, DraftChangeIssue, DraftChangeResult, DraftInsertionSide, DraftSchedule } from './draft-schedule'
import type { ReviewStore } from './history-review'
import type { DraftState } from './use-draft-schedule'
import { sameSource } from './workbook'
import type { Source, Workbook } from './workbook'
import type { SavedDraft } from './workbook-session'

export type DraftBlock = { source: Source; name: string; label: string; start: string; months: string[]; id: string; anchor: HTMLButtonElement }
export type DraftCell = Pick<DraftBlock, 'source' | 'start' | 'months'> & { leave?: boolean; label: string }
export type DraftDestination = DraftCell & { side?: DraftInsertionSide }
type ReleasedMove = { from: DraftBlock; focus: DraftBlock; anchor: HTMLElement; keyboard: boolean; kind: 'insert' | 'swap'; blocks: (string | undefined)[] | null; description: string }

function sameBlock(a: DraftCell | null | undefined, b: DraftCell | null | undefined) {
  return !!a && !!b && sameSource(a.source, b.source) && a.start === b.start
}

export function draftDestinationError(from: DraftBlock, next: DraftDestination) {
  if (!sameSource(from.source, next.source)) return `Choose a block in ${from.name}’s row.`
  if (next.leave) return 'This period is recorded leave. A posting cannot be assigned during leave.'
  if (!next.months.length) return 'Choose another generated posting block.'
  if (!next.side && from.months.length !== next.months.length) {
    return `Only equal-length blocks can swap. These blocks span ${from.months.length} and ${next.months.length} training months.`
  }
  return ''
}

export function focusBlock(block: DraftBlock) {
  const candidate = block.anchor.isConnected && block.anchor.id === block.id ? block.anchor : document.getElementById(block.id)
  const target = candidate instanceof HTMLButtonElement && !candidate.disabled ? candidate : document.getElementById('resident-search')
  target?.focus({ preventScroll: true })
}

export function issuesForCell(issues: DraftChangeIssue[], source: Source, months: string[]) {
  return issues.filter((issue) => issue.affected.some((cell) => sameSource(cell.source, source) && months.includes(cell.month)))
}

export function useDraftBlockEditing(workbook: Workbook, store: ReviewStore, draft: DraftSchedule | null, disabled: boolean,
  { getSavedResult, applyChange }: Pick<DraftState, 'getSavedResult' | 'applyChange'>) {
  const [editor, setEditor] = useState<DraftBlock | null>(null)
  const [move, setMove] = useState<{ from: DraftBlock; keyboard: boolean } | null>(null)
  const moving = useRef(move)
  const target = useRef<DraftDestination | null>(null)
  const [destination, setDestination] = useState<DraftDestination | null>(null)
  const [released, setReleased] = useState<ReleasedMove | null>(null)
  const [returning, setReturning] = useState<ReleasedMove | null>(null)
  const [preview, setPreview] = useState<DraftChangeResult | null>(null)
  const [checking, setChecking] = useState(false)
  const proposed = released?.blocks && (checking || (preview && draftSwapOutcome(preview) === 'warning')) ? released : null
  const [announcement, announce] = useState('')
  const [context, setContext] = useState({ workbook, store, draft, disabled })
  const active = useRef<{ controller: AbortController; prepared?: { previous: SavedDraft; next: SavedDraft; issues: DraftChangeIssue[] } } | null>(null)
  if (context.workbook !== workbook || context.store !== store || context.draft !== draft || context.disabled !== disabled) {
    if (move || released) announce('')
    setContext({ workbook, store, draft, disabled })
    setEditor(null); setMove(null); setDestination(null); setReleased(null); setReturning(null); setPreview(null); setChecking(false)
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
    return () => active.current?.controller.abort()
  }, [workbook, store, draft, disabled])

  function openEditor(block: DraftBlock) {
    if (disabled) return
    if (proposed) setReturning(proposed)
    stopMove(); clearPreview(); setEditor(block)
  }

  function closeEditor() {
    clearPreview(); setEditor(null)
    if (editor) requestAnimationFrame(() => focusBlock(editor))
  }

  function startMove(from: DraftBlock, keyboard: boolean) {
    if (disabled) return
    if (proposed) setReturning(proposed)
    cancelMove()
    const next = { from, keyboard }
    moving.current = next; setMove(next)
    if (keyboard) announce(`Picked up ${from.label}. Use the arrow keys to choose a swap, Shift and an arrow key to insert, Enter to apply, or Escape to cancel.`)
  }

  function cancelMove() {
    stopMove(); clearPreview()
  }

  function cancelForUndo() {
    cancelMove(); setEditor(null); setReturning(null); announce('')
  }

  function announceUndo(name: string | null | undefined) {
    announce(name ? `Undid the last change to ${name}’s draft.` : 'Undid the last draft change.')
  }

  function check(change: DraftChange, affected: DraftCell[], release?: ReleasedMove) {
    clearPreview()
    const previous = getSavedResult()
    if (!draft || previous?.data !== draft || disabled) return
    const operation: NonNullable<typeof active.current> = { controller: new AbortController() }
    active.current = operation
    setChecking(true)
    const action = change.kind === 'insert' ? 'move' : 'swap'
    if (release) announce(`Checking the ${action}.`)
    const { signal } = operation.controller
    void (async () => {
      let result: DraftChangeResult
      try {
        result = await validateDraftChange(workbook, store, draft, change, signal)
        if (!signal.aborted && active.current === operation && result.draft && draftSwapOutcome(result) !== 'blocked') {
          const next = await prepareDraftEdit(previous, change, result.draft,
            (base, step) => validateDraftChange(workbook, store, base, step, signal))
          operation.prepared = { previous, next, issues: result.issues }
        }
      } catch (error) {
        result = { draft: null, issues: [{ severity: 'hard', code: 'validation_error',
          message: error instanceof Error && !['AbortError', 'TimeoutError', 'TypeError'].includes(error.name)
            ? error.message : 'Could not check this change. Try again.',
          affected: affected.map(({ start, source }) => ({ month: start, source })) }] }
      }
      if (signal.aborted || active.current !== operation) return
      const outcome = draftSwapOutcome(result)
      if (release && outcome === 'clean') {
        if (await applyReleased(release) || signal.aborted || active.current !== operation) return
      }
      if (release?.blocks && outcome !== 'warning') setReturning(release)
      setPreview(result); setChecking(false)
      if (release) {
        announce(outcome === 'warning' ? `Review the ${action} warning before applying.`
          : result.issues.map((issue) => issue.message).join(' ') || `Could not apply this ${action}. Try again.`)
      }
    })()
  }

  function selectDestination(next: DraftDestination | null) {
    const held = moving.current
    if (!held || (target.current === next || (sameBlock(target.current, next) && target.current?.side === next?.side))) return
    target.current = next; setDestination(next)
    if (held.keyboard && next) {
      announce(sameBlock(held.from, next) ? 'Original position.'
        : draftDestinationError(held.from, next) || (next.side ? `Insert ${held.from.label} ${next.side} ${next.label}.` : `Swap with ${next.label}.`))
    }
  }

  function apply(block: DraftBlock) {
    const prepared = active.current?.prepared
    if (!prepared || !applyChange(prepared.previous, prepared.next)) return false
    cancelMove(); setEditor(null); setReturning(null)
    announce(`${block.name}’s draft updated.${prepared.issues.length ? ` ${prepared.issues.map((issue) => issue.message).join(' ')}` : ''}`)
    requestAnimationFrame(() => focusBlock(block))
    return true
  }

  async function applyReleased(release: ReleasedMove) {
    const operation = active.current
    if (!operation?.prepared) return false
    // A fast response can arrive while the cards are still moving into place.
    await new Promise(requestAnimationFrame)
    const layer = release.anchor.closest('tr')?.querySelector('.draft-move-preview')
    await Promise.allSettled(layer?.getAnimations({ subtree: true }).map((animation) => animation.finished) ?? [])
    return release.anchor.isConnected && active.current === operation && apply(release.focus)
  }

  function finishDrag() {
    if (!moving.current || moving.current.keyboard) return
    cancelMove()
  }

  function drop(next: DraftDestination, anchor: HTMLElement) {
    const held = moving.current
    if (!held) return
    const { from, keyboard } = held
    if (sameBlock(from, next)) { cancelMove(); return }
    const kind = next.side ? 'insert' : 'swap'
    const row = draft?.residents.find((person) => sameSource(person.source, from.source))
    const insertion = next.side && row && sameSource(from.source, next.source)
      ? draftInsertion(row.months, from.start, next.start, next.side) : null
    if (insertion && !insertion.changed) { cancelMove(); announce('Original position.'); return }
    const movedIndex = insertion?.blocks.indexOf(from.start) ?? -1
    const focusMonth = row?.months[movedIndex]?.month ?? next.start
    const focus = { ...from, id: `${from.id.slice(0, -7)}${focusMonth}` }
    const message = draftDestinationError(from, next)
    const blocks = message || !row ? null : next.side ? insertion?.blocks ?? null : draftSwapLayout(row.months, from.start, next.start)
    const movedBlocks = row && blocks ? [...new Set(blocks.filter((start, index) => start && start !== row.months[index].block_start))] : []
    const description = movedBlocks.map((start) => {
      const label = row?.months.find((month) => month.block_start === start)?.label
      const months = row?.months.filter((_, index) => blocks?.[index] === start).map((month) => month.month) ?? []
      return `${monthRanges(months)}, ${label}.`
    }).join(' ')
    const release = { from, focus, anchor, keyboard, kind, blocks, description } as const
    setReturning(null)
    target.current = next; setDestination(next)
    moving.current = null; setMove(null); setReleased(release)
    if (message) {
      clearPreview()
      setPreview({ draft: null, issues: [{ severity: 'hard', code: 'invalid_destination', message,
        affected: [from, next].map(({ source, start }) => ({ source, month: start })) }] })
      announce(message)
      return
    }
    const change = { resident: from.source, start: from.start, destination: next.start }
    check(next.side ? { ...change, kind: 'insert', side: next.side } : { ...change, kind: 'swap' }, [from, next], release)
  }

  function dismissDrop(restoreFocus = true) {
    if (!released) return
    if (proposed) setReturning(proposed)
    cancelMove(); announce(checking ? 'Move cancelled.' : '')
    if (restoreFocus) focusBlock(released.from)
  }

  function confirmDrop() {
    if (released && !checking && preview && draftSwapOutcome(preview) === 'warning') void applyReleased(released)
  }

  function finishReturn(release: ReleasedMove) {
    setReturning((current) => current === release ? null : current)
  }

  function endKeyboardMove(restoreFocus: boolean) {
    const from = moving.current?.from
    cancelMove(); announce('Move cancelled.')
    if (restoreFocus && from) focusBlock(from)
  }

  return { editor, openEditor, closeEditor, move, moving, destination, released, proposed, returning, finishReturn, preview, checking, announcement,
    clearPreview, check, startMove, selectDestination, apply, drop, dismissDrop, confirmDrop, finishDrag, endKeyboardMove, cancelForUndo, announceUndo }
}
