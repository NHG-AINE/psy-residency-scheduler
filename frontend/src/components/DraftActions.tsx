import { useId, useLayoutEffect, useRef } from 'react'
import type { DraftState } from '../lib/use-draft-schedule'
import type { Source, Workbook } from '../lib/workbook'
import DraftReview from './DraftReview'
import DraftSearchLimit from './DraftSearchLimit'
import DraftTimer from './DraftTimer'

export default function DraftActions({ state, workbook, yearLabel, exporting, checkingUndo, onExport, onUndo, onDiscard, onFind }: {
  state: DraftState; workbook: Workbook; yearLabel: string; exporting: boolean; checkingUndo: boolean
  onUndo: () => void; onExport: () => void; onDiscard: () => void; onFind: (source: Source) => void
}) {
  const actions = useRef<HTMLDivElement>(null)
  const primary = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const menuId = useId()
  const focusAction = useRef(false)
  const press = useRef<{ input: 'pointer' | 'keyboard'; ready: boolean } | null>(null)
  const unavailable = exporting || state.pending || checkingUndo
  const pendingStop = state.cancelling || state.finishing
  useLayoutEffect(() => {
    if (!focusAction.current) return
    if (document.activeElement === document.body || actions.current?.contains(document.activeElement)) {
      primary.current?.focus({ preventScroll: true })
    }
    if (!state.busy) focusAction.current = false
  }, [state.busy, state.draft])

  function generate() {
    focusAction.current = true
    void state.generate()
  }

  if (!state.canGenerate) return null
  return <div className="draft-actions" ref={actions}>
    <span className="sr-only" role="status">{state.busy && !state.cancelling
      ? state.finishing ? 'Preparing draft…' : state.ready ? 'A feasible draft is ready to use.' : '' : ''}</span>
    {state.busy ? <>
      <span className="draft-running" role="status">{state.draft ? 'Regenerating draft' : 'Generating draft'}</span>
      <DraftTimer draft={state.draft} startedAt={state.startedAt} elapsedSeconds={state.elapsedSeconds} />
      <button key="draft-stop" ref={primary} type="button" className={`button draft-stop${state.ready && !state.cancelling ? '' : ' button-secondary'}`} aria-disabled={pendingStop}
        onPointerDown={(event) => {
          if (event.isPrimary && event.button === 0) press.current = { input: 'pointer', ready: state.ready }
        }}
        onPointerCancel={() => { press.current = null }}
        onKeyDown={(event) => {
          if (!event.repeat && (event.key === ' ' || event.key === 'Enter')) press.current = { input: 'keyboard', ready: state.ready }
          if (event.key === 'Enter' && event.repeat) event.preventDefault()
        }}
        onBlur={() => { press.current = null }}
        onClick={(event) => {
          const input = event.detail === 0 ? 'keyboard' : 'pointer'
          const useCurrent = press.current?.input === input ? press.current.ready : state.ready
          press.current = null
          if (pendingStop) return
          if (useCurrent) void state.finishGeneration()
          else void state.cancelGeneration()
        }}>
        {state.cancelling ? 'Cancelling…' : state.finishing ? 'Preparing draft…' : state.ready ? 'Use current draft' : 'Cancel generation'}
      </button>
    </> : state.draft ? <>
      {!!state.draft.edit_options?.length && <button type="button" className="button button-secondary" disabled={unavailable || !state.canUndo}
        data-draft-undo onClick={onUndo}>Undo last change</button>}
      <DraftReview key={workbook.target_year} draft={state.draft} workbook={workbook} yearLabel={yearLabel} onFind={onFind} />
      <button ref={primary} type="button" className="button" disabled={unavailable} onClick={onExport}>
        {exporting ? 'Exporting…' : 'Export Excel'}
      </button>
      <button type="button" className="button button-secondary year-arrow draft-overflow" aria-label="Draft actions" title="Draft actions"
        disabled={unavailable} popoverTarget={menuId} onClick={(event) => {
          const panel = menu.current
          if (!panel) return
          const { right, top, bottom } = event.currentTarget.getBoundingClientRect()
          const below = window.innerHeight - bottom
          panel.style.right = `${Math.max(8, window.innerWidth - right)}px`
          panel.style.top = below >= 110 || top < 110 ? `${bottom + 6}px` : 'auto'
          panel.style.bottom = below < 110 && top >= 110 ? `${window.innerHeight - top + 6}px` : 'auto'
        }}>
        <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="3" cy="8" r="1.2" /><circle cx="8" cy="8" r="1.2" /><circle cx="13" cy="8" r="1.2" /></svg>
      </button>
      <div className="draft-menu" id={menuId} ref={menu} popover="auto">
        <button type="button" onClick={() => { menu.current?.hidePopover(); generate() }}>Regenerate draft</button>
        <button type="button" onClick={() => { menu.current?.hidePopover(); focusAction.current = true; onDiscard() }}>Discard draft</button>
      </div>
    </> : <>
      <DraftSearchLimit value={state.searchSeconds} onChange={state.setSearchSeconds} disabled={state.pending} />
      <button ref={primary} type="button" className="button" disabled={state.pending} onClick={generate}>Generate draft</button>
    </>}
  </div>
}
