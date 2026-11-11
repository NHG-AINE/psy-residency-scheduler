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
  const stages = draftTiming(draft)
  const reached = stages.filter((stage) => stage.seconds !== undefined)
  const waiting = stages.filter((stage) => stage.seconds === undefined)
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
      <div className="timing-bar" aria-hidden="true">{reached.map((stage, index) => <span key={stage.priority}
        className={stage.status === 'optimal' ? '' : 'timing-limited'}
        style={{ flexGrow: stage.seconds, animationDelay: `${index * 35}ms` }} />)}</div>
      <ol className="timing-stages">{reached.map((stage) => <li key={stage.priority} className={stage.status === 'optimal' ? '' : 'timing-limited'}>
        <div className="timing-stage-title"><span>{stage.label}</span><span>{stage.seconds!.toFixed(1)} s</span></div>
        <p>{stage.outcome}</p>
        {stage.status === 'unknown' && <small>Draft retained from the previous stage.</small>}
      </li>)}</ol>
      {waiting.length > 0 && <details className="timing-remaining"><summary>{waiting.length} later {waiting.length === 1 ? 'stage' : 'stages'} not reached</summary>
        <ul>{waiting.map((stage) => <li key={stage.priority}>{stage.label}</li>)}</ul>
      </details>}
    </div>
  </>
}
