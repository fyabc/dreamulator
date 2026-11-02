/** useElementSize — observe an element's pixel size (the fullscreen sky needs
 *  real pixel dimensions so the perspective projection's field of view means
 *  what it says at any viewport aspect).
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export interface ElementSize {
  width: number
  height: number
}

export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [size, setSize] = useState<ElementSize | null>(null)

  const measure = useCallback((el: T) => {
    const rect = el.getBoundingClientRect()
    if (rect.width > 0 && rect.height > 0) {
      setSize({ width: Math.round(rect.width), height: Math.round(rect.height) })
    }
  }, [])

  const setRef = useCallback(
    (el: T | null) => {
      ref.current = el
      if (el) measure(el)
    },
    [measure],
  )

  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) return
      const { width, height } = entry.contentRect
      if (width > 0 && height > 0) {
        setSize({ width: Math.round(width), height: Math.round(height) })
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
    // Attach once on mount (the callback ref has already resolved by then).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [measure])

  return { ref: setRef, size }
}
