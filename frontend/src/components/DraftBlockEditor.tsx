import { useId, useLayoutEffect, useRef, useState } from 'react'
import { draftPostingChoices, draftSwapOutcome, monthRanges } from '../lib/draft-schedule'
import type { DraftChangeIssue, DraftChangeResult, DraftEditOption } from '../lib/draft-schedule'
import type { DraftBlock } from '../lib/use-draft-block-editing'
import { sameSource } from '../lib/workbook'
import type { Source } from '../lib/workbook'

function positionPanel(panel: HTMLElement, anchor: HTMLElement, centered = false) {
  const { clientWidth: width, clientHeight: height } = document.documentElement
  const rect = anchor.getBoundingClientRect()
  const box = panel.getBoundingClientRect()
  const below = height - rect.bottom
  const above = rect.top
  const top = centered ? (height - box.height) / 2 : below >= box.height + 8 || below >= above ? rect.bottom + 8 : rect.top - box.height - 8
  const left = centered ? (width - box.width) / 2 : rect.left
  panel.style.top = `${Math.max(12, Math.min(top, height - box.height - 12))}px`
  panel.style.left = `${Math.max(12, Math.min(left, width - box.width - 12))}px`
}

function DraftIssueMessages({ issues }: { issues: DraftChangeIssue[] }) {
  if (!issues.length) return null
  if (issues.length === 1) return <p className={issues[0].severity}>{issues[0].message}</p>
  return <ul className="draft-issue-list">
    {issues.map((issue, index) => <li key={`${issue.code}-${index}`} className={issue.severity}>{issue.message}</li>)}
  </ul>
}

export function DraftSwapFeedback({ anchor, checking, preview, onApply, onDismiss }: {
  anchor: HTMLElement; checking: boolean; preview: DraftChangeResult | null; onApply: () => void; onDismiss: () => void
}) {
  const id = useId()
  const panel = useRef<HTMLDivElement>(null)
  const dismissButton = useRef<HTMLButtonElement>(null)
  const issues = preview?.issues ?? []
  const blocked = !checking && (!preview || draftSwapOutcome(preview) !== 'warning')
  const title = checking ? 'Checking the swap…' : blocked ? 'Swap blocked' : issues.length > 1 ? 'Review swap warnings' : 'Review swap warning'
  useLayoutEffect(() => {
    const popup = panel.current
    if (!popup || !anchor.isConnected) return
    popup.showPopover()
    const position = () => positionPanel(popup, anchor)
    position()
    const observer = new ResizeObserver(position)
    observer.observe(popup)
    window.addEventListener('resize', position)
    document.addEventListener('scroll', position, true)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', position)
      document.removeEventListener('scroll', position, true)
      popup.hidePopover()
    }
  }, [anchor])
  useLayoutEffect(() => {
    if (!checking) dismissButton.current?.focus({ preventScroll: true })
  }, [checking])
  useLayoutEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      event.preventDefault()
      onDismiss()
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [onDismiss])
  return <div ref={panel} popover="manual" role="dialog" className={`draft-block-editor draft-swap-feedback${blocked ? ' hard' : ''}`}
    aria-labelledby={`${id}-title`} aria-describedby={`${id}-details`}>
    <h3 id={`${id}-title`}>{title}</h3>
    <div id={`${id}-details`} className="draft-editor-feedback">
      {checking ? <p>The postings will stay in place while the swap is checked.</p>
        : issues.length ? <DraftIssueMessages issues={issues} />
          : <p>Could not apply this swap. Try again.</p>}
    </div>
    <footer>
      <button type="button" ref={dismissButton} className="button button-secondary" onClick={onDismiss}>{blocked ? 'Dismiss' : 'Cancel'}</button>
      {!checking && !blocked && <button type="button" className="button" onClick={onApply}>Apply swap</button>}
    </footer>
  </div>
}

export default function DraftBlockEditor({ block, options, current, years, checking, canApply, issues, onSelect, onApply, onClose }: {
  block: DraftBlock; options: DraftEditOption[]; current?: Source; years: string; checking: boolean; canApply: boolean
  issues: DraftChangeIssue[]; onSelect: (option: DraftEditOption | null) => void; onApply: () => void; onClose: () => void
}) {
  const id = useId()
  const dialog = useRef<HTMLDialogElement>(null)
  const postingSelect = useRef<HTMLSelectElement>(null)
  const [posting, setPosting] = useState('')
  const [site, setSite] = useState('')
  const choices = draftPostingChoices(options, years)
  const offers = choices.find((choice) => choice.key === posting)?.offers ?? []
  const picked = offers.find((offer) => JSON.stringify(offer.source) === site)

  useLayoutEffect(() => {
    const panel = dialog.current
    if (!panel) return
    panel.showModal()
    postingSelect.current?.focus({ preventScroll: true })
    const position = () => positionPanel(panel, block.anchor, window.matchMedia('(max-width: 640px)').matches)
    position()
    const observer = new ResizeObserver(position)
    observer.observe(panel)
    window.addEventListener('resize', position)
    document.addEventListener('scroll', position, true)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', position)
      document.removeEventListener('scroll', position, true)
      panel.close()
    }
  }, [block])

  return <dialog className="draft-block-editor" ref={dialog} aria-labelledby={`${id}-title`} aria-describedby={`${id}-context`}
    onCancel={(event) => { event.preventDefault(); onClose() }}
    onClick={(event) => {
      if (event.target !== event.currentTarget) return
      const rect = event.currentTarget.getBoundingClientRect()
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose()
    }}>
    <header>
      <div><h3 id={`${id}-title`}>Edit posting block</h3><p id={`${id}-context`}>{block.name} · {monthRanges(block.months)}</p></div>
      <button type="button" className="draft-editor-close" aria-label="Close posting editor" onClick={onClose}>
        <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 4 8 8m0-8-8 8" /></svg>
      </button>
    </header>
    <form onSubmit={(event) => { event.preventDefault(); if (canApply && picked && !checking) onApply() }}>
      <label>Posting<select ref={postingSelect} value={posting} onChange={(event) => {
        setPosting(event.target.value); setSite(''); onSelect(null)
      }}>
        <option value="">Choose a posting</option>
        {choices.map(({ key, label }) => <option value={key} key={key}>{label}</option>)}
      </select></label>
      {!!offers.length && <label className="draft-editor-institution">Institution<select value={site} onChange={(event) => {
        setSite(event.target.value)
        const option = offers.find((offer) => JSON.stringify(offer.source) === event.target.value)
        onSelect(option && (!sameSource(option.source, current) || option.source.column !== current?.column) ? option : null)
      }}>
        <option value="">Choose an institution</option>
        {offers.map((option) => {
          const key = JSON.stringify(option.source)
          const multiple = offers.filter((offer) => offer.institution === option.institution).length > 1
          return <option key={key} value={key}>{option.institution}{multiple ? ` (${option.residency_year})` : ''}</option>
        })}
      </select></label>}
      <div className="draft-editor-feedback" role="status">
        {checking && <p>Checking posting change…</p>}
        <DraftIssueMessages issues={issues} />
      </div>
      <footer><button type="submit" className="button" disabled={!picked || !canApply || checking}>Apply edit</button></footer>
    </form>
  </dialog>
}

export function DraftBlockReasons({ issues, label, descriptionId, show }: { issues: DraftChangeIssue[]; label: string; descriptionId: string; show: boolean }) {
  const anchor = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const blocked = issues.some((issue) => issue.severity === 'hard')
  const title = blocked ? 'Change blocked' : issues.length > 1 ? 'Draft warnings' : 'Draft warning'
  const keepOpen = useRef(false)
  function open() {
    const popup = panel.current
    if (!popup || !anchor.current) return
    if (!popup.matches(':popover-open')) popup.showPopover()
    positionPanel(popup, anchor.current)
  }
  function close() { panel.current?.hidePopover(); keepOpen.current = false }
  const summary = issues.map((issue) => issue.message).join(' ')
  useLayoutEffect(() => { if (show) open(); else close() }, [show, summary])
  useLayoutEffect(() => {
    const dismiss = (event: Event) => {
      if (event.type === 'keydown' && (event as KeyboardEvent).key !== 'Escape') return
      if (event.type === 'pointerdown' && anchor.current?.contains(event.target as Node)) return
      close()
    }
    document.addEventListener('scroll', dismiss, true)
    document.addEventListener('keydown', dismiss)
    document.addEventListener('pointerdown', dismiss)
    window.addEventListener('resize', dismiss)
    return () => {
      document.removeEventListener('scroll', dismiss, true)
      document.removeEventListener('keydown', dismiss)
      document.removeEventListener('pointerdown', dismiss)
      window.removeEventListener('resize', dismiss)
    }
  }, [])
  return <>
    <button type="button" ref={anchor} className="draft-block-flag" aria-label={`${title} for ${label}`} aria-describedby={descriptionId}
      onFocus={open} onBlur={close} onPointerEnter={open} onPointerLeave={() => { if (!show && !keepOpen.current && document.activeElement !== anchor.current) close() }}
      onClick={() => { if (keepOpen.current) close(); else { keepOpen.current = true; open() } }}>
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 2 15 14H1Z" /><path d="M8 6v4m0 2v.5" /></svg>
    </button>
    <span id={descriptionId} className="sr-only">{title}. {summary}</span>
    <div ref={panel} popover="manual" className={`draft-block-reason ${blocked ? 'hard' : 'soft'}`} aria-hidden="true">
      <strong>{title}</strong>
      <DraftIssueMessages issues={issues} />
    </div>
  </>
}
