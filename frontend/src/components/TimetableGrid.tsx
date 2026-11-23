import { useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

function isTruncated(label: Element) {
  return label.scrollWidth > label.clientWidth
}

export default function TimetableGrid({ children }: { children: ReactNode }) {
  const grid = useRef<HTMLDivElement>(null)
  const popup = useRef<HTMLDivElement>(null)
  const [hovered, setHovered] = useState<HTMLElement | null>(null)
  const [focused, setFocused] = useState<HTMLElement | null>(null)
  const active = hovered ?? focused

  useLayoutEffect(() => {
    const labels = grid.current?.querySelectorAll('.posting-name')
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
    const panel = popup.current
    const scrollArea = grid.current
    if (!active || !panel || !scrollArea) return
    const viewport = document.documentElement
    const position = () => {
      const label = active.querySelector('.posting-name')
      const rect = active.getBoundingClientRect()
      const clip = scrollArea.getBoundingClientRect()
      const outside = rect.right <= Math.max(clip.left, 0) || rect.left >= Math.min(clip.right, viewport.clientWidth) ||
        rect.bottom <= Math.max(clip.top, 0) || rect.top >= Math.min(clip.bottom, viewport.clientHeight)
      if (!label || !isTruncated(label) || outside) {
        panel.hidePopover()
        return
      }
      panel.textContent = active.dataset.postingTooltip ?? ''
      if (!panel.matches(':popover-open')) panel.showPopover()
      const { width, height } = panel.getBoundingClientRect()
      const margin = 8
      const left = rect.left + (rect.width - width) / 2
      const above = rect.top - height
      const top = above >= margin ? above : rect.bottom
      panel.style.left = `${Math.max(margin, Math.min(left, viewport.clientWidth - width - margin))}px`
      panel.style.top = `${Math.max(margin, Math.min(top, viewport.clientHeight - height - margin))}px`
    }
    position()
    function onScroll() {
      setHovered(null)
      position()
    }
    function dismiss(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setHovered(null)
        setFocused(null)
      }
    }
    document.addEventListener('keydown', dismiss)
    document.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      document.removeEventListener('keydown', dismiss)
      document.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
    }
  }, [active, children])

  function postingAt(target: EventTarget | null) {
    if (!(target instanceof Element)) return null
    if (popup.current?.contains(target)) return active
    const button = target.closest<HTMLButtonElement>('button')
    if (button) return button.hasAttribute('data-posting-tooltip') ? button : null
    return target.closest<HTMLElement>('[data-posting-tooltip]')
  }

  return <div className="table-scroll timetable" ref={grid}
    onPointerOver={(event) => {
      const posting = postingAt(event.target)
      const label = posting?.querySelector('.posting-name')
      if (event.pointerType !== 'touch' && posting !== postingAt(event.relatedTarget)) {
        setHovered(label && isTruncated(label) ? posting : null)
      }
    }}
    onPointerOut={(event) => {
      if (event.pointerType !== 'touch' && postingAt(event.target) !== postingAt(event.relatedTarget)) setHovered(null)
    }}
    onFocus={(event) => {
      if (event.target.matches('[data-posting-tooltip]:focus-visible')) setFocused(event.target)
    }}
    onBlur={(event) => { if (event.target === focused) setFocused(null) }}
    onClick={() => { setHovered(null); setFocused(null) }}>
    {children}
    {active && <div className="posting-tooltip" ref={popup} popover="manual" role="tooltip" aria-hidden="true" />}
  </div>
}
