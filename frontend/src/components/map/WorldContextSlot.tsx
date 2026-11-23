import { useEffect, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { WORLD_CONTEXT_CONTROLS_ID } from '../world/WorldContext'

/** Portals map-level controls into the global world/branch bar. */
export default function WorldContextSlot({ children }: { children: ReactNode }) {
  const [host, setHost] = useState<HTMLElement | null>(null)
  useEffect(() => {
    setHost(document.getElementById(WORLD_CONTEXT_CONTROLS_ID))
  }, [])
  return host ? createPortal(children, host) : null
}
