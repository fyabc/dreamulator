/** Time state for the sky view: a committed value (URL + full query) and a
 *  live value (drag/play, fast path), with URL sync gated during
 *  interaction (the usePlanetViewState sun-sweep precedent: continuous rAF
 *  ⇒ one replace on stop, not one per frame).
 *
 *  Play speed is expressed in the observer's OWN solar days per real second
 *  — the same unit the on-screen dial uses, so "0.1 太阳日/秒" visibly means
 *  "the dial advances 2.4 hours per second".  Playback runs unbounded (no
 *  year wrap); the typed input is the only way to set the instant.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

export interface SkyTimeState {
  /** Committed time (URL ?at=, full query incl. events), in Earth days. */
  atCommitted: number
  /** Live time while dragging/playing; equals atCommitted when idle. */
  atLive: number
  /** True while dragging or playing (fast-path polling active). */
  interacting: boolean
  playing: boolean
  /** Play speed in observer solar days per real second. */
  playSpeedSolarDaysPerSec: number
  /** Set the live time only (scrubbing — fast path, no commit). */
  setLive: (days: number) => void
  /** Set and commit (typed input — full query + URL write). */
  setAt: (days: number) => void
  beginDrag: () => void
  endDrag: (days?: number) => void
  setPlaying: (playing: boolean) => void
  setPlaySpeed: (solarDaysPerSec: number) => void
  /** Feed the observer's solar-day length (render-time latest-value ref —
   *  the data that provides it also depends on this hook). */
  setSolarDay: (solarDayDays: number | null) => void
}

const DEFAULT_SPEED_SOLAR_PER_SEC = 0.08
/** Fallback day length when the engine reports none (Earth days). */
const FALLBACK_SOLAR_DAY = 1

export function useSkyTime(): SkyTimeState {
  const [searchParams, setSearchParams] = useSearchParams()
  const initial = Number(searchParams.get('at') ?? '0')
  const [atCommitted, setAtCommitted] = useState(Number.isFinite(initial) ? initial : 0)
  const [atLive, setAtLive] = useState(atCommitted)
  const [dragging, setDragging] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(DEFAULT_SPEED_SOLAR_PER_SEC)
  const solarDayRef = useRef<number>(FALLBACK_SOLAR_DAY)

  // URL sync — suppressed while interacting (drag/play), one write on stop.
  useEffect(() => {
    if (dragging || playing) return
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (atCommitted !== 0) next.set('at', String(atCommitted))
        else next.delete('at')
        return next
      },
      { replace: true },
    )
  }, [atCommitted, dragging, playing, setSearchParams])

  const commit = useCallback((days: number) => {
    setAtLive(days)
    setAtCommitted(days)
  }, [])

  const setAt = useCallback(commit, [commit])

  const setLive = useCallback((days: number) => setAtLive(days), [])

  const beginDrag = useCallback(() => setDragging(true), [])

  const endDrag = useCallback(
    (days?: number) => {
      setDragging(false)
      commit(days ?? atLiveRef.current)
    },
    [commit],
  )
  // Keep a ref so endDrag without an argument commits the latest live value.
  const atLiveRef = useRef(atLive)
  atLiveRef.current = atLive

  const setPlayingState = useCallback((next: boolean) => {
    setPlaying(next)
    if (!next) {
      setDragging(false)
      setAtCommitted(atLiveRef.current)
    }
  }, [])

  const setPlaySpeed = useCallback((solarDaysPerSec: number) => setSpeed(solarDaysPerSec), [])

  const setSolarDay = useCallback((solarDayDays: number | null) => {
    solarDayRef.current = solarDayDays ?? FALLBACK_SOLAR_DAY
  }, [])

  // Play: rAF sweep advancing atLive by `speed` solar days per real second,
  // unbounded.  66 ms soft throttle — 15 Hz is far beyond what the sky
  // visibly changes between frames; the advance uses the elapsed time since
  // the last EMIT (not the last frame), so throttling never slows the clock.
  useEffect(() => {
    if (!playing) return
    let raf = 0
    let lastEmit = performance.now()
    const loop = (now: number) => {
      if (now - lastEmit >= 66) {
        const dt = (now - lastEmit) / 1000
        lastEmit = now
        setAtLive((v) => v + speed * solarDayRef.current * dt)
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [playing, speed])

  const interacting = dragging || playing
  return {
    atCommitted,
    atLive,
    interacting,
    playing,
    playSpeedSolarDaysPerSec: speed,
    setLive,
    setAt,
    beginDrag,
    endDrag,
    setPlaying: setPlayingState,
    setPlaySpeed,
    setSolarDay,
  }
}
