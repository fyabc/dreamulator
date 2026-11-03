/** Marker colors for the sky chart.
 *
 * Color is physical, not categorical: stars carry their black-body
 * temperature color (viewers/utils/starColor.ts), every non-star body shares
 * one neutral tone, and selection/hover reuse the repo-wide viewer
 * conventions (#f0c040 / #4da6ff).  Identity comes from labels and the
 * inspector, never from a 15-hue palette.
 */

import * as THREE from 'three'
import { temperatureToColor } from '../../viewers/utils/starColor'

/** Star marker fill from its effective temperature (black-body color). */
export function starColorCss(temperatureK: number | null | undefined): string {
  const kelvin = temperatureK ?? 5800
  const color: THREE.Color = temperatureToColor(kelvin)
  return `#${color.getHexString()}`
}

/** Neutral fill for planets / moons / dwarfs on the dark chart surface. */
export const BODY_FILL = '#8fa3c8'
/** Lit-region overlay tint (phase crescent), warm on the dark surface. */
export const LIT_FILL = '#f4e3b2'
/** Selection ring + hover ring (repo viewer conventions). */
export const SELECTED_STROKE = '#f0c040'
export const HOVER_STROKE = '#4da6ff'
/** Cardinal north accent (GlobeViewer polar-axis precedent). */
export const NORTH_ACCENT = '#e57373'
/** Dark-sky halo shared by cardinals, the zenith caption and body labels:
 *  readable over rings and discs without a backing box. */
export const TEXT_HALO = {
  stroke: '#030308',
  strokeWidth: 2.5,
  paintOrder: 'stroke' as const,
  strokeLinejoin: 'round' as const,
}
/** Ground fill for the pan view's below-horizon region — a quiet navy that
 *  still reads as "ground" against the near-black sky. */
export const GROUND_FILL = '#141430'
