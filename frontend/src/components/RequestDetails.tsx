import { useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import type { RequestOutcome } from '../lib/draft-schedule'
import { monthLabel, sourceLabel } from '../lib/workbook'

export default function RequestDetails({ name, rows, hint, className, children }: {
  name: string; rows: RequestOutcome[]; hint: string; className: string; children: ReactNode
}) {
  const id = useId()
  const panel = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    const close = (event: Event) => {
      if (event.target instanceof Node && panel.current?.contains(event.target)) return
      panel.current?.hidePopover()
    }
    window.addEventListener('resize', close)
    document.addEventListener('scroll', close, true)
    return () => {
      window.removeEventListener('resize', close)
      document.removeEventListener('scroll', close, true)
    }
  }, [open])
  function position() {
    if (!panel.current || !trigger.current) return
    const rect = trigger.current.getBoundingClientRect()
    const below = window.innerHeight - rect.bottom - 16
    const above = rect.top - 16
    const width = Math.min(384, window.innerWidth - 32)
    Object.assign(panel.current.style, {
      left: `${Math.max(16, Math.min(rect.left, window.innerWidth - width - 16))}px`,
      top: below >= above ? `${rect.bottom + 8}px` : 'auto',
      bottom: below >= above ? 'auto' : `${window.innerHeight - rect.top + 8}px`,
      maxHeight: `${Math.max(80, Math.max(above, below))}px`,
    })
  }
  return <>
    <button ref={trigger} type="button" className={className} popoverTarget={id}
      aria-haspopup="dialog" aria-expanded={open} aria-label={`${name}: ${hint}`} title={hint}
      onClick={position}>{children}</button>
    <div ref={panel} id={id} popover="auto" role="dialog" aria-labelledby={`${id}-title`}
      className="request-popover" onToggle={(event) => {
        const opening = event.newState === 'open'
        setOpen(opening)
        if (opening) event.currentTarget.querySelector('button')?.focus({ preventScroll: true })
      }}>
      <header><h3 id={`${id}-title`}>{name}</h3>
        <button type="button" className="request-close" popoverTarget={id} popoverTargetAction="hide" aria-label="Close request details">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 4 8 8m0-8-8 8" /></svg>
        </button>
      </header>
      {rows.map((row, index) => <article key={index}>
        <p className={`request-status ${row.status}`}>{row.status === 'met' ? 'Request met' : row.status === 'not_met' ? 'Request not met' : 'Pending clarification'}</p>
        <dl><dt>Requested</dt><dd>{row.request.posting_request}<small>{row.request.period || 'Any time in planning year'}</small></dd>
          {!!row.assigned?.length && <><dt>Assigned</dt><dd>{row.assigned.map((item, i) => <div key={i}>{item.label}<small>{item.months.map(monthLabel).join(', ')}</small></div>)}</dd></>}
        </dl>
        {row.reason && <p className="request-reason">{row.reason}</p>}
        <small className="source">{sourceLabel(row.request.source)}</small>
      </article>)}
    </div>
  </>
}
