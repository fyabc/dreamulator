import { useCallback, useEffect, useRef, useState } from 'react'

export function useIdleChrome(held: boolean, delayMs = 2600) {
  const [visible, setVisible] = useState(true)
  const timerRef = useRef<number | undefined>(undefined)

  const poke = useCallback(() => {
    setVisible(true)
    window.clearTimeout(timerRef.current)
    if (!held) timerRef.current = window.setTimeout(() => setVisible(false), delayMs)
  }, [held, delayMs])

  useEffect(() => {
    poke()
    return () => window.clearTimeout(timerRef.current)
  }, [poke])

  return { visible: visible || held, poke }
}
