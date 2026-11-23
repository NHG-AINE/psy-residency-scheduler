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
  const unavailable = exporting || state.pending || checkingUndo
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
    {state.busy ? <>
      <span className="draft-running" role="status">{state.draft ? 'Regenerating draft' : 'Generating draft'}</span>
      <DraftTimer draft={state.draft} startedAt={state.startedAt} elapsedSeconds={state.elapsedSeconds} />
      <button ref={primary} type="button" className="button button-secondary" disabled={state.cancelling} onClick={() => void state.cancelGeneration()}>
        {state.cancelling ? 'Cancelling…' : 'Cancel generation'}
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
