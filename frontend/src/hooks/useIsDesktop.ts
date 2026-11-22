import { useEffect, useState } from 'react'

const QUERY = '(min-width: 1024px)'

/**
 * True while the viewport is at the desktop layout breakpoint (lg, 1024 px).
 * Pages use it to mount only one of their mobile/desktop layouts: keeping both
 * mounted means two WebGL contexts and two full texture sets, which is enough
 * to lose the context (black canvas) on phones.
 */
export default function useIsDesktop(): boolean {
  const [desktop, setDesktop] = useState(() =>
    typeof window === 'undefined' || typeof window.matchMedia !== 'function'
      ? true : window.matchMedia(QUERY).matches)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const query = window.matchMedia(QUERY)
    const update = () => setDesktop(query.matches)
    update()
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])
  return desktop
}
