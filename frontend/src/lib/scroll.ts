let stopCurrent: (() => void) | undefined

export function scrollToPosition(top: number) {
  stopCurrent?.()
  const start = window.scrollY
  const end = Math.max(0, Math.min(top, document.documentElement.scrollHeight - window.innerHeight))
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    window.scrollTo({ top: end, behavior: 'instant' })
    return () => {}
  }
  const started = performance.now()
  let frame = 0
  const cancel = () => {
    cancelAnimationFrame(frame)
    window.removeEventListener('wheel', cancel)
    window.removeEventListener('touchstart', cancel)
    window.removeEventListener('keydown', cancel)
    window.removeEventListener('pointerdown', cancel)
    if (stopCurrent === cancel) stopCurrent = undefined
  }
  const animate = (now: number) => {
    const progress = Math.min((now - started) / 700, 1)
    const eased = progress < 0.5 ? 4 * progress ** 3 : 1 - (-2 * progress + 2) ** 3 / 2
    window.scrollTo({ top: start + (end - start) * eased, behavior: 'instant' })
    if (progress < 1) frame = requestAnimationFrame(animate)
    else cancel()
  }
  window.addEventListener('wheel', cancel, { passive: true })
  window.addEventListener('touchstart', cancel, { passive: true })
  window.addEventListener('keydown', cancel)
  window.addEventListener('pointerdown', cancel)
  stopCurrent = cancel
  frame = requestAnimationFrame(animate)
  return cancel
}
