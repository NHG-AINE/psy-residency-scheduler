let stopCurrent: (() => void) | undefined

export function scrollToPosition(top: number, onComplete?: () => void) {
  const end = clamp(top, document.documentElement.scrollHeight - window.innerHeight)
  return scrollTogether([{ start: window.scrollY, end, apply: (top) => window.scrollTo({ top, behavior: 'instant' }) }], onComplete)
}

function clamp(value: number, max: number) {
  return Math.max(0, Math.min(value, max))
}

function scrollTogether(positions: { start: number; end: number; apply: (value: number) => void }[], onComplete?: () => void,
  duration = 700, onInterrupt?: () => void) {
  stopCurrent?.()
  if (positions.every(({ start, end }) => Math.abs(end - start) < 1) || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    positions.forEach(({ end, apply }) => apply(end))
    onComplete?.()
    return () => {}
  }
  const started = performance.now()
  let frame = 0
  const interrupt = () => { cancel(); onInterrupt?.() }
  const cancel = () => {
    cancelAnimationFrame(frame)
    window.removeEventListener('wheel', cancel)
    window.removeEventListener('touchstart', cancel)
    window.removeEventListener('keydown', cancel)
    window.removeEventListener('pointerdown', cancel)
    if (stopCurrent === interrupt) stopCurrent = undefined
  }
  const animate = (now: number) => {
    const progress = Math.min((now - started) / duration, 1)
    const eased = progress < 0.5 ? 4 * progress ** 3 : 1 - (-2 * progress + 2) ** 3 / 2
    positions.forEach(({ start, end, apply }) => apply(start + (end - start) * eased))
    if (progress < 1) frame = requestAnimationFrame(animate)
    else { cancel(); onComplete?.() }
  }
  if (!onInterrupt) {
    window.addEventListener('wheel', cancel, { passive: true })
    window.addEventListener('touchstart', cancel, { passive: true })
    window.addEventListener('keydown', cancel)
    window.addEventListener('pointerdown', cancel)
  }
  stopCurrent = interrupt
  frame = requestAnimationFrame(animate)
  return cancel
}

function revealOffset(start: number, end: number, low: number, high: number) {
  if (end - start > high - low) return start < low || start >= high ? start - low : 0
  return start < low ? start - low : end > high ? end - high : 0
}

export function revealTimetableCells(row: HTMLTableRowElement, cells: Element[], onComplete: () => void, onInterrupt: () => void) {
  const grid = row.closest<HTMLElement>('.timetable')
  const header = grid?.querySelector('thead th')
  const resident = row.querySelector('th')
  if (!grid || !header || !resident || !cells.length) { onComplete(); return () => {} }
  const bounds = grid.getBoundingClientRect()
  const rowBounds = row.getBoundingClientRect()
  const rects = cells.map((cell) => cell.getBoundingClientRect())
  const top = clamp(grid.scrollTop + revealOffset(rowBounds.top, rowBounds.bottom,
    bounds.top + header.getBoundingClientRect().height, bounds.top + grid.clientHeight), grid.scrollHeight - grid.clientHeight)
  const left = clamp(grid.scrollLeft + revealOffset(Math.min(...rects.map((rect) => rect.left)), Math.max(...rects.map((rect) => rect.right)),
    resident.getBoundingClientRect().right, bounds.left + grid.clientWidth), grid.scrollWidth - grid.clientWidth)
  const finalTop = rowBounds.top - (top - grid.scrollTop)
  const finalBottom = finalTop + rowBounds.height
  const pageOffset = revealOffset(finalTop, finalBottom, 0, window.innerHeight)
  if (Math.abs(top - grid.scrollTop) < 1 && Math.abs(left - grid.scrollLeft) < 1 && !pageOffset) {
    onComplete()
    return () => {}
  }
  const pageTop = clamp(window.scrollY + (pageOffset ? revealOffset(finalTop, finalBottom, 8, window.innerHeight - 8) : 0),
    document.documentElement.scrollHeight - window.innerHeight)
  const positions = [
    { start: grid.scrollTop, end: top, apply: (top: number) => { grid.scrollTop = top } },
    { start: grid.scrollLeft, end: left, apply: (left: number) => { grid.scrollLeft = left } },
    { start: window.scrollY, end: pageTop, apply: (top: number) => window.scrollTo({ top, behavior: 'instant' }) },
  ]
  const distance = Math.max(...positions.map(({ start, end }) => Math.abs(end - start)))
  return scrollTogether(positions, onComplete, Math.min(450, Math.max(140, distance * 0.55)), onInterrupt)
}
