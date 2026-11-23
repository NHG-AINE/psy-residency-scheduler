import { useId, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

function isTruncated(label: Element) {
  return label.scrollWidth > label.clientWidth
}

const triggerSelector = '[data-status-tooltip], [data-posting-tooltip]'

export function PostingStatus({ className, label, details, children, descriptionId, interactive = false }: {
  className: string; label: string; details: ReactNode; children: ReactNode; descriptionId?: string; interactive?: boolean
}) {
  const id = useId()
  const tooltipId = descriptionId ?? id
  return <>
    <button type="button" className={className} aria-label={label}
      aria-describedby={interactive ? undefined : tooltipId} aria-haspopup={interactive ? 'dialog' : undefined}
      aria-expanded={interactive ? false : undefined}
      data-status-tooltip={tooltipId}>{children}</button>
    <div id={tooltipId} className="posting-tooltip posting-status-tooltip" popover="manual"
      role={interactive ? 'dialog' : 'tooltip'} aria-label={interactive ? label : undefined}>{details}</div>
  </>
}

export default function TimetableGrid({ children, suppressTooltip = false }: { children: ReactNode; suppressTooltip?: boolean }) {
  const grid = useRef<HTMLDivElement>(null)
  const popup = useRef<HTMLDivElement>(null)
  const visiblePanel = useRef<HTMLElement | null>(null)
  const [hovered, setHovered] = useState<HTMLElement | null>(null)
  const [focused, setFocused] = useState<HTMLElement | null>(null)
  const [tapped, setTapped] = useState<HTMLElement | null>(null)
  const [suppressed, setSuppressed] = useState(suppressTooltip)
  const active = suppressTooltip ? null : tapped ?? hovered ?? focused

  function clear() {
    setHovered(null)
    setFocused(null)
    setTapped(null)
  }
  if (suppressed !== suppressTooltip) {
    setSuppressed(suppressTooltip)
    if (suppressTooltip) clear()
  }

  function postingAt(target: EventTarget | null) {
    if (!(target instanceof Element)) return null
    const button = target.closest<HTMLButtonElement>('button')
    if (button) return button.matches(triggerSelector) ? button : null
    return target.closest<HTMLElement>(triggerSelector)
  }

  useLayoutEffect(() => {
    const labels = grid.current?.querySelectorAll('[data-posting-tooltip] > .posting-name')
    if (!labels?.length) return
    function sync(label: Element) {
      if (label.parentElement instanceof HTMLButtonElement) return
      if (isTruncated(label)) label.parentElement?.setAttribute('tabindex', '0')
      else label.parentElement?.removeAttribute('tabindex')
    }
    const observer = new ResizeObserver((entries) => entries.forEach(({ target }) => sync(target)))
    labels.forEach((label) => {
      sync(label)
      observer.observe(label)
    })
    let observing = true
    void document.fonts.ready.then(() => { if (observing) labels.forEach(sync) })
    return () => { observing = false; observer.disconnect() }
  }, [children])

  useLayoutEffect(() => {
    const id = active?.dataset.statusTooltip
    const panel = id ? document.getElementById(id) : popup.current
    const scrollArea = grid.current
    if (!active?.isConnected || !panel || !scrollArea) return
    visiblePanel.current = panel
    const viewport = document.documentElement
    const position = () => {
      const label = active.querySelector('.posting-name')
      const rect = active.getBoundingClientRect()
      const clip = scrollArea.getBoundingClientRect()
      const outside = rect.right <= Math.max(clip.left, 0) || rect.left >= Math.min(clip.right, viewport.clientWidth) ||
        rect.bottom <= Math.max(clip.top, 0) || rect.top >= Math.min(clip.bottom, viewport.clientHeight)
      if ((!id && (!label || !isTruncated(label))) || outside) {
        panel.hidePopover()
        if (active.hasAttribute('aria-haspopup')) active.setAttribute('aria-expanded', 'false')
        return
      }
      if (!id) panel.textContent = active.dataset.postingTooltip ?? ''
      if (!panel.matches(':popover-open')) panel.showPopover()
      if (active.hasAttribute('aria-haspopup')) active.setAttribute('aria-expanded', 'true')
      const margin = 8
      const above = rect.top - margin
      const below = viewport.clientHeight - rect.bottom - margin
      const onTop = panel.scrollHeight + 2 <= above || above >= below
      panel.style.maxHeight = `${Math.max(0, onTop ? above : below)}px`
      const { width, height } = panel.getBoundingClientRect()
      const left = rect.left + (rect.width - width) / 2
      const top = onTop ? rect.top - height : rect.bottom
      panel.style.left = `${Math.max(margin, Math.min(left, viewport.clientWidth - width - margin))}px`
      panel.style.top = `${Math.max(margin, Math.min(top, viewport.clientHeight - height - margin))}px`
    }
    position()
    const onScroll = (event: Event) => {
      if (event.target instanceof Node && panel.contains(event.target)) return
      setHovered(null)
      setTapped(null)
      position()
    }
    const dismiss = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (panel.contains(document.activeElement)) active.focus({ preventScroll: true })
        clear()
      }
    }
    const observer = new ResizeObserver(position)
    observer.observe(panel)
    document.addEventListener('keydown', dismiss)
    document.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      panel.hidePopover()
      if (active.hasAttribute('aria-haspopup')) active.setAttribute('aria-expanded', 'false')
      visiblePanel.current = null
      observer.disconnect()
      document.removeEventListener('keydown', dismiss)
      document.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
    }
  }, [active, children])

  useLayoutEffect(() => {
    function dismissOutside(event: PointerEvent) {
      if (!(event.target instanceof Element) || !grid.current?.contains(event.target)) { clear(); return }
      if (visiblePanel.current?.contains(event.target)) return
      const anchor = postingAt(event.target)
      if (!anchor?.dataset.statusTooltip) { clear(); return }
      if (event.pointerType === 'touch') {
        setHovered(null)
        setFocused(null)
        setTapped((previous) => previous === anchor ? null : anchor)
      }
    }
    document.addEventListener('pointerdown', dismissOutside)
    return () => document.removeEventListener('pointerdown', dismissOutside)
  }, [])

  function anchorAt(target: EventTarget | null) {
    return target instanceof Node && visiblePanel.current?.contains(target) ? active : postingAt(target)
  }

  return <div className="table-scroll timetable" ref={grid}
    onPointerOver={(event) => {
      const posting = anchorAt(event.target)
      const label = posting?.querySelector('.posting-name')
      if (event.pointerType !== 'touch' && posting !== anchorAt(event.relatedTarget)) {
        setHovered(posting?.dataset.statusTooltip || (label && isTruncated(label)) ? posting : null)
      }
    }}
    onPointerOut={(event) => {
      if (event.pointerType !== 'touch' && anchorAt(event.target) !== anchorAt(event.relatedTarget)) setHovered(null)
    }}
    onFocus={(event) => {
      if (active && visiblePanel.current?.contains(event.target)) setFocused(active)
      else if (event.target.matches(':focus-visible') && event.target.matches(triggerSelector)) setFocused(event.target)
    }}
    onBlur={(event) => {
      if (event.relatedTarget instanceof Node && visiblePanel.current?.contains(event.relatedTarget)) return
      if (visiblePanel.current?.contains(event.target) && event.relatedTarget === active) return
      if (visiblePanel.current?.contains(event.target)) { clear(); return }
      if (event.target === focused) setFocused(null)
      if (event.target === hovered) setHovered(null)
      if (event.target === tapped) setTapped(null)
    }}
    onClick={(event) => {
      const anchor = anchorAt(event.target)
      if (!anchor?.dataset.statusTooltip) { clear(); return }
      if (event.detail === 0 && anchor.contains(event.target as Node)) {
        visiblePanel.current?.querySelector('summary')?.focus()
      }
    }}
    onDragStart={clear}>
    {children}
    <div className="posting-tooltip" ref={popup} popover="manual" role="tooltip" aria-hidden="true" />
  </div>
}
