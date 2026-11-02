/** Data hooks for the sky view: a react-query for the committed instant
 *  (full, with events) and a latest-wins fast fetch while interacting
 *  (include_events=false, ~ms server-side; single in-flight, abortable).
 */

import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { api, fetchSkyFast } from '../../api/client'
import type { SkyEphemerisResult } from './types'

export interface SkyDataParams {
  worldName: string
  observerId: string | null
  branch: string | null
  lat: number
  lon: number
  atCommitted: number
  atLive: number
  interacting: boolean
}

export interface SkyDataState {
  /** The result to render (fast while interacting, full when idle). */
  display: SkyEphemerisResult | undefined
  /** True while the fast path has a newer instant than the full query. */
  fastActive: boolean
  error: Error | null
  isLoading: boolean
}

export function useSkyData(params: SkyDataParams): SkyDataState {
  const { worldName, observerId, branch, lat, lon, atCommitted, atLive, interacting } = params

  const query = useQuery({
    queryKey: ['sky', worldName, observerId, branch, lat, lon, atCommitted],
    queryFn: () =>
      api.getSky(worldName, {
        from: observerId ?? undefined,
        lat,
        lon,
        at: atCommitted,
        branch,
      }),
    enabled: !!worldName && !!observerId,
    retry: false,
    staleTime: 5 * 60_000,
  })

  // Fast path — one in flight, latest wins (probeSeq precedent).
  const [fast, setFast] = useState<SkyEphemerisResult | undefined>(undefined)
  const seqRef = useRef(0)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (!interacting || !observerId) {
      seqRef.current += 1 // invalidate any in-flight fast result
      abortRef.current?.abort()
      return
    }
    const seq = ++seqRef.current
    const controller = new AbortController()
    abortRef.current = controller
    fetchSkyFast(worldName, { from: observerId, lat, lon, at: atLive, branch }, controller.signal)
      .then((result) => {
        if (seq === seqRef.current) setFast(result)
      })
      .catch(() => {
        /* aborted or superseded — the next drag tick supersedes anyway */
      })
    return () => controller.abort()
    // atLive changes fast during interaction; the seq guard keeps this safe.
  }, [worldName, observerId, branch, lat, lon, atLive, interacting])

  // The fast result belongs to one observation scope; drop it when the scope
  // (not the instant) changes so a stale sky can never linger.
  const scopeKey = `${worldName}|${observerId}|${branch}|${lat}|${lon}`
  useEffect(() => {
    setFast(undefined)
  }, [scopeKey])

  // Display: the full query is authoritative — but while interacting (the
  // committed instant deliberately lags the live one) and while the full
  // result for a just-committed instant is still ~1 s away, the fast result
  // keeps the sky live.  Without the interacting guard the stale full result
  // for the old committed instant would win and playback would freeze.
  const fullIsCurrent =
    !interacting &&
    query.data !== undefined &&
    Math.abs(query.data.at_days - atCommitted) < 1e-9
  const display = fullIsCurrent ? query.data : (fast ?? query.data)

  return {
    display,
    fastActive: !fullIsCurrent && fast !== undefined,
    error: query.error ?? null,
    isLoading: query.isLoading,
  }
}
