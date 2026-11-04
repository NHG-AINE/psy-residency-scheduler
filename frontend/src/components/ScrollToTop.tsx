import { useEffect, useRef, useState } from 'react'
import { scrollToPosition } from '../lib/scroll'

export default function ScrollToTop() {
  const [visible, setVisible] = useState(false)
  const cancelScroll = useRef<(() => void) | undefined>(undefined)
  useEffect(() => {
    const update = () => setVisible(window.scrollY > window.innerHeight)
    update()
    window.addEventListener('scroll', update, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update)
      window.removeEventListener('resize', update)
      cancelScroll.current?.()
    }
  }, [])

  function goToTop() {
    // Move keyboard focus out of the control before it disappears near the top.
    document.querySelector<HTMLElement>('main')?.focus({ preventScroll: true })
    cancelScroll.current = scrollToPosition(0)
  }

  return <div className={`scroll-to-top ${visible ? 'is-visible' : ''}`} inert={!visible}>
    <button type="button" aria-label="Scroll to top" onClick={goToTop}>
      <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 16V4M4.5 9.5 10 4l5.5 5.5" /></svg>
      <span>Top</span>
    </button>
  </div>
}
