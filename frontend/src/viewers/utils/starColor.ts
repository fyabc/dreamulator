/**
 * Black-body radiation → RGB color conversion.
 *
 * Based on Tanner Helland's algorithm:
 * http://www.tannerhelland.com/4435/photography- Calculating-blackbody-rgb/
 *
 * Input: temperature in Kelvin (1000–40000 K range is physically meaningful)
 * Output: Three.js Color-compatible { r, g, b } in [0, 1]
 */

import * as THREE from 'three'

/**
 * Convert a black-body temperature (Kelvin) to an RGB color.
 *
 * The algorithm fits piecewise curves to Planckian locus data,
 * producing visually accurate colors for stellar rendering.
 */
export function temperatureToColor(temperatureK: number): THREE.Color {
  // Clamp to a reasonable range
  const temp = Math.max(1000, Math.min(40000, temperatureK)) / 100

  let r: number, g: number, b: number

  // Red channel
  if (temp <= 66) {
    r = 255
  } else {
    r = 329.698727446 * Math.pow(temp - 60, -0.1332047592)
  }

  // Green channel
  if (temp <= 66) {
    g = 99.4708025861 * Math.log(temp) - 161.1195681661
  } else {
    g = 288.1221695283 * Math.pow(temp - 60, -0.0755148492)
  }

  // Blue channel
  if (temp >= 66) {
    b = 255
  } else if (temp <= 19) {
    b = 0
  } else {
    b = 138.5177312231 * Math.log(temp - 10) - 305.0447927307
  }

  // Clamp to [0, 255] then normalize to [0, 1]
  r = Math.max(0, Math.min(255, r)) / 255
  g = Math.max(0, Math.min(255, g)) / 255
  b = Math.max(0, Math.min(255, b)) / 255

  return new THREE.Color(r, g, b)
}

/**
 * Get a glow intensity factor based on stellar luminosity.
 * Returns a value in [0.5, 3.0] suitable for emissive intensity.
 */
export function luminosityToGlowIntensity(luminosity: number): number {
  // Log scale to compress the huge range of stellar luminosities
  return Math.max(0.5, Math.min(3.0, 0.5 + Math.log10(1 + luminosity) * 0.8))
}
