/** Pure helpers for the universe-setting layer (split from SkyBackground.tsx
 *  so the component file only exports the component — react-refresh).
 */

/** Limiting magnitude rises as the field narrows (the zoom-linked limit
 *  planetariums use): a tighter field earns ~2 magnitudes of depth at 9×. */
export function backgroundLimit(baseLimit: number, fovDeg: number | null): number {
  const boost = fovDeg === null ? 1 : Math.max(0, 2 * Math.log10(90 / fovDeg))
  return baseLimit + Math.min(boost, 4)
}

/** Star dot radius in chart pixels: brighter = bigger, clamped to a point
 *  source.  Calibrated BELOW the system-body scale on purpose: the faintest
 *  system body (a −5 mag moon) outshines the brightest background star by
 *  ~100×, and the chart must read that hierarchy. */
export function starDotRadius(magnitude: number, limit: number): number {
  return Math.min(2.4, Math.max(0.5, 0.5 + (limit - magnitude) * 0.28))
}

/** Star dot opacity: the naked-eye fade, capped well below a lit planet disc. */
export function starDotAlpha(magnitude: number, limit: number): number {
  return Math.min(0.8, Math.max(0.1, 0.12 + (limit - magnitude) * 0.11))
}
