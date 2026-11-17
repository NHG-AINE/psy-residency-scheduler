import { useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { scrollToPosition } from '../lib/scroll'

const REVEAL_PAUSE_MS = 350

export default function DetailsPopover({ name, hint, className, children, details, openRequest = 0 }: {
  name: string; hint: string; className: string; children: ReactNode; details: ReactNode; openRequest?: number
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
    const left = Math.max(16, Math.min(rect.left, window.innerWidth - width - 16))
    Object.assign(panel.current.style, {
      left: `${left}px`,
      transformOrigin: `${Math.max(0, Math.min(width, rect.left + rect.width / 2 - left))}px ${below >= above ? 'top' : 'bottom'}`,
      top: below >= above ? `${rect.bottom + 8}px` : 'auto',
      bottom: below >= above ? 'auto' : `${window.innerHeight - rect.top + 8}px`,
      maxHeight: `${Math.max(80, Math.max(above, below))}px`,
    })
  }
  useEffect(() => {
    if (!openRequest) return
    const rect = trigger.current?.getBoundingClientRect()
    if (!rect) return
    panel.current?.hidePopover()
    let frame = 0
    let timer = 0
    let cancelScroll: (() => void) | undefined
    const interruptions = ['pointerdown', 'keydown', 'wheel', 'touchstart', 'resize']
    const cancel = () => {
      cancelScroll?.()
      clearTimeout(timer)
      cancelAnimationFrame(frame)
      interruptions.forEach((event) => window.removeEventListener(event, cancel))
    }
    const show = () => {
      const delay = window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : REVEAL_PAUSE_MS
      timer = window.setTimeout(() => {
        frame = requestAnimationFrame(() => {
          position()
          panel.current?.showPopover()
          cancel()
        })
      }, delay)
    }
    // Reveal the institution first, then let its cell settle before
    // opening the popup. A new interaction cancels the pending reveal.
    interruptions.forEach((event) => window.addEventListener(event, cancel, { passive: true }))
    const offset = rect.top < 24 ? rect.top - 24 : rect.bottom > window.innerHeight - 24 ? rect.bottom - window.innerHeight + 24 : 0
    if (offset) cancelScroll = scrollToPosition(window.scrollY + offset, show)
    else show()
    return cancel
  }, [openRequest])
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
        <button type="button" className="request-close" popoverTarget={id} popoverTargetAction="hide" aria-label="Close details">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 4 8 8m0-8-8 8" /></svg>
        </button>
      </header>
      {details}
    </div>
  </>
}
