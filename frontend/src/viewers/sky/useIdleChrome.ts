/** useIdleChrome — Stellarium-posture chrome visibility: any pointer activity
 *  reveals the overlays, then they fade after an idle delay.  Panels pin the
 *  chrome while the pointer is inside them (enter/leave counter), and modal
 *  state (an open dialog) holds it on until released.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export interface IdleChrome {
  visible: boolean
  /** Pointer entered (true) / left (false) a chrome panel. */
  pin: (pinned: boolean) => void
  /** Modal hold (dialog open) — chrome stays until released. */
  hold: (held: boolean) => void
  /** Reveal now and restart the idle timer. */
  poke: () => void
}

export function useIdleChrome(delayMs = 2600): IdleChrome {
  const [visible, setVisible] = useState(true)
  const pinnedRef = useRef(0)
  const heldRef = useRef(false)
  const timerRef = useRef<number | undefined>(undefined)

  const scheduleHide = useCallback(() => {
    window.clearTimeout(timerRef.current)
    if (pinnedRef.current > 0 || heldRef.current) return
    timerRef.current = window.setTimeout(() => setVisible(false), delayMs)
  }, [delayMs])

  const poke = useCallback(() => {
    setVisible(true)
    scheduleHide()
  }, [scheduleHide])

  useEffect(() => {
    window.addEventListener('pointermove', poke)
    window.addEventListener('pointerdown', poke)
    poke()
    return () => {
      window.removeEventListener('pointermove', poke)
      window.removeEventListener('pointerdown', poke)
      window.clearTimeout(timerRef.current)
    }
  }, [poke])

  const pin = useCallback(
    (pinned: boolean) => {
      pinnedRef.current = Math.max(0, pinnedRef.current + (pinned ? 1 : -1))
      if (pinnedRef.current > 0) setVisible(true)
      else scheduleHide()
    },
    [scheduleHide],
  )

  const hold = useCallback(
    (held: boolean) => {
      heldRef.current = held
      if (held) {
        window.clearTimeout(timerRef.current)
        setVisible(true)
      } else scheduleHide()
    },
    [scheduleHide],
  )

  return { visible: visible || heldRef.current, pin, hold, poke }
}
