/**
 * useRafCoalesced — coalesce a fast-changing value to at most one update
 * per animation frame.
 *
 * Layer opacity sliders fire dozens of input events per second; each one
 * used to trigger a full CPU texture re-bake (~100s of ms).  Consumers
 * (useGPUTerrain) receive this coalesced value instead, so the expensive
 * re-bake runs at most once per frame while the slider itself stays fully
 * responsive (panel state updates immediately).
 */

import { useEffect, useRef, useState } from 'react'

export default function useRafCoalesced<T>(value: T): T {
  const [synced, setSynced] = useState(value)
  const latestRef = useRef(value)
  latestRef.current = value

  useEffect(() => {
    const id = requestAnimationFrame(() => setSynced(latestRef.current))
    return () => cancelAnimationFrame(id)
  }, [value])

  return synced
}
