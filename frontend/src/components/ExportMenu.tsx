import { useEffect, useId, useRef } from 'react'
import type { KeyboardEvent, RefObject } from 'react'

export type ExcelExport = 'current' | 'next'

export default function ExportMenu({ latestYear, hasDraft, includeDraft, disabled, exporting, onExport, buttonRef }: {
  latestYear: number; hasDraft: boolean; includeDraft: boolean; disabled: boolean; exporting: ExcelExport | null
  onExport: (kind: ExcelExport) => void; buttonRef: RefObject<HTMLButtonElement | null>
}) {
  const id = useId()
  const menu = useRef<HTMLDivElement>(null)
  const startAtEnd = useRef(false)
  const items = () => Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])
  const unavailable = disabled || exporting !== null
  const followingYear = `${latestYear + 1}–${String(latestYear + 2).slice(-2)}`

  function position() {
    const panel = menu.current
    const trigger = buttonRef.current
    if (!panel?.matches(':popover-open') || !trigger) return
    const { right, top, bottom } = trigger.getBoundingClientRect()
    const below = window.innerHeight - bottom
    const above = below < panel.scrollHeight + 14 && top > below
    const maxRight = window.innerWidth - panel.offsetWidth - 8
    panel.style.right = `${Math.max(8, Math.min(maxRight, window.innerWidth - right))}px`
    panel.style.top = above ? 'auto' : `${bottom + 6}px`
    panel.style.bottom = above ? `${window.innerHeight - top + 6}px` : 'auto'
    panel.style.maxHeight = `${Math.max(0, (above ? top : below) - 14)}px`
    panel.style.transformOrigin = above ? 'bottom right' : 'top right'
  }

  useEffect(() => {
    function dismiss() { menu.current?.hidePopover() }
    window.addEventListener('resize', dismiss)
    window.addEventListener('scroll', dismiss)
    return () => {
      window.removeEventListener('resize', dismiss)
      window.removeEventListener('scroll', dismiss)
    }
  }, [])

  function move(event: KeyboardEvent<HTMLDivElement>) {
    const options = items()
    const index = options.indexOf(document.activeElement as HTMLButtonElement)
    if (event.key === 'Escape') {
      event.preventDefault()
      menu.current?.hidePopover()
      buttonRef.current?.focus()
    } else if (event.key === 'Tab') {
      // Let the browser move focus from the trigger in the normal tab order.
      menu.current?.hidePopover()
      buttonRef.current?.focus()
    } else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault()
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
        : (index + (event.key === 'ArrowDown' ? 1 : options.length - 1)) % options.length
      options[next]?.focus()
    }
  }

  function choose(kind: ExcelExport) {
    menu.current?.hidePopover()
    buttonRef.current?.focus()
    onExport(kind)
  }

  return <>
    <button ref={buttonRef} type="button" className={`button export-trigger${hasDraft ? '' : ' button-secondary'}`} popoverTarget={id}
      aria-haspopup="menu" aria-disabled={unavailable} onClick={(event) => {
        if (unavailable) event.preventDefault()
      }} onKeyDown={(event) => {
        if (unavailable || !['ArrowDown', 'ArrowUp'].includes(event.key)) return
        event.preventDefault()
        startAtEnd.current = event.key === 'ArrowUp'
        menu.current?.showPopover({ source: event.currentTarget })
      }}>
      {exporting === 'next' ? 'Preparing workbook…' : exporting === 'current' ? 'Exporting…' : 'Export Excel'}
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
    </button>
    <div className="draft-menu export-menu" id={id} ref={menu} popover="auto" role="menu" aria-label="Export Excel" onKeyDown={move}
      onToggle={(event) => {
        if (event.newState !== 'open') return
        position()
        items().at(startAtEnd.current ? -1 : 0)?.focus({ preventScroll: true })
        startAtEnd.current = false
      }}>
      <button type="button" role="menuitem" tabIndex={-1} disabled={unavailable} onClick={() => choose('current')}>
        Export current workbook
      </button>
      <button type="button" role="menuitem" tabIndex={-1} disabled={unavailable} onClick={() => choose('next')}>
        Prepare {followingYear} workbook
        <small>{includeDraft ? 'Carry residents forward from the latest draft.' : 'Carry residents forward from the latest worksheet.'}</small>
        <small>Start with blank postings and requests.</small>
      </button>
    </div>
  </>
}
