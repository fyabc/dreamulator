/**
 * useSeasonTimelapse — seasonal cycle playback for the map / globe
 * (video materials feature).
 *
 * Advances the season angle one month (30°) every `monthMs` while playing —
 * the same discrete semantics as dragging the season slider, so the URL
 * `?season=` write-back fires only 12 times per cycle.  Monthly data is
 * inherently 12 discrete bins (N×12 arrays), so there is no "in-between"
 * month to interpolate; a continuous rAF sweep would only churn the lighting
 * without adding data resolution.
 *
 * When paused, the month follows the slider again (the user can scrub to a
 * new start position and resume from there).
 */

import { useEffect, useRef } from 'react'

/** Season-month index (0 = March vernal equinox) from the season angle. */
function monthOf(deg: number): number {
  return ((Math.round(deg / 30) % 12) + 12) % 12
}

interface UseSeasonTimelapseArgs {
  /** Combined enable (play toggle && monthly mode). */
  playing: boolean
  /** Milliseconds per month step. */
  monthMs: number
  /** Current season angle — only read while paused, to re-align the resume point. */
  seasonDeg: number
  onSeasonChange: (deg: number) => void
}

export function useSeasonTimelapse({ playing, monthMs, seasonDeg, onSeasonChange }: UseSeasonTimelapseArgs): void {
  const monthRef = useRef(monthOf(seasonDeg))
  const cbRef = useRef(onSeasonChange)
  cbRef.current = onSeasonChange

  // While paused, track slider moves so playback resumes from the visible
  // month instead of jumping back to where it stopped.
  useEffect(() => {
    if (!playing) monthRef.current = monthOf(seasonDeg)
  }, [seasonDeg, playing])

  useEffect(() => {
    if (!playing) return
    let timer = 0
    const tick = () => {
      monthRef.current = (monthRef.current + 1) % 12
      cbRef.current(monthRef.current * 30)
      timer = window.setTimeout(tick, monthMs)
    }
    // First step waits a full beat so the current month is shown for its
    // full duration before advancing.
    timer = window.setTimeout(tick, monthMs)
    return () => window.clearTimeout(timer)
  }, [playing, monthMs])
}
