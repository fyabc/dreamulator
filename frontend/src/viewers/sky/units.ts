/** Display formatting for sky-view quantities whose magnitudes span many
 *  decades (irradiance from a star down to a faint moonshine).  SI-prefix
 *  auto-scaling keeps three significant digits without a decimal sprawl.
 */

const IRRADIANCE_STEPS: Array<[number, string]> = [
  [1e3, 'kW/m²'],
  [1, 'W/m²'],
  [1e-3, 'mW/m²'],
  [1e-6, 'µW/m²'],
  [1e-9, 'nW/m²'],
]

/** Irradiance in W/m² rendered with an SI prefix: 2.9e-5 → "29.0 µW/m²". */
export function formatIrradiance(wPerM2: number): string {
  if (!Number.isFinite(wPerM2)) return '—'
  if (wPerM2 === 0) return '0 W/m²'
  const abs = Math.abs(wPerM2)
  for (const [floor, unit] of IRRADIANCE_STEPS) {
    if (abs >= floor) return `${(wPerM2 / floor).toPrecision(3)} ${unit}`
  }
  return `${(wPerM2 / 1e-12).toPrecision(3)} pW/m²`
}
