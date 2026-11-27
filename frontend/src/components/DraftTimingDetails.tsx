import { useEffect, useId, useRef, useState } from 'react'
import type { DraftSchedule } from '../lib/draft-schedule'
import { draftTiming } from '../lib/draft-timing'

export default function DraftTimingDetails({ draft, elapsedSeconds, duration }: {
  draft: DraftSchedule; elapsedSeconds: number; duration: string
}) {
  const id = useId()
  const panel = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const phases = draftTiming(draft)
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
    const width = Math.min(430, window.innerWidth - 32)
    Object.assign(panel.current.style, {
      left: `${Math.max(16, Math.min(rect.right - width, window.innerWidth - width - 16))}px`,
      top: below >= above ? `${rect.bottom + 8}px` : 'auto',
      bottom: below >= above ? 'auto' : `${window.innerHeight - rect.top + 8}px`,
      maxHeight: `${Math.max(80, Math.max(above, below))}px`,
    })
  }
  return <>
    <span className="draft-timer">Generated in <button ref={trigger} type="button" className="draft-timing-trigger" popoverTarget={id}
      aria-haspopup="dialog" aria-expanded={open} aria-label={`Generated in ${duration}. View generation timing`}
      onClick={position}>{duration}</button></span>
    <div ref={panel} id={id} popover="auto" role="dialog" aria-labelledby={`${id}-title`}
      className="request-popover draft-timing" onToggle={(event) => {
        const opening = event.newState === 'open'
        setOpen(opening)
        if (opening) event.currentTarget.querySelector('button')?.focus({ preventScroll: true })
      }}>
      <header><h3 id={`${id}-title`}>Generation timing</h3>
        <button type="button" className="request-close" popoverTarget={id} popoverTargetAction="hide" aria-label="Close generation timing">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 4 8 8m0-8-8 8" /></svg>
        </button>
      </header>
      <div className="timing-total"><div><strong>{elapsedSeconds.toFixed(1)}<span> s</span></strong><small>total elapsed</small></div>
        {draft.wall_time_seconds !== undefined && <small>{draft.wall_time_seconds.toFixed(1)} s solver time</small>}
      </div>
      <div className="timing-bar" aria-hidden="true">{phases.map((phase, index) => <span key={phase.id}
        className={phase.complete ? '' : 'timing-limited'}
        style={{ flexGrow: phase.seconds, animationDelay: `${index * 35}ms` }} />)}</div>
      <ol className="timing-stages">{phases.map((phase) => <li key={phase.id} className={phase.complete ? '' : 'timing-limited'}>
        <span>{phase.label}</span><span>{phase.seconds.toFixed(1)} s</span>
      </li>)}</ol>
    </div>
  </>
}
