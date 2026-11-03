/** Phase-crescent SVG geometry for sky-chart body markers.
 *
 * Classic construction: the illuminated region is bounded by the limb
 * semicircle through the bright pole plus the terminator ellipse (semi-axis
 * r perpendicular to the star direction, r·|2k−1| along it).  k is the
 * illuminated fraction (1 full, 0.5 half, 0 new); the bright pole points at
 * the star on the sky, so the caller passes the screen-space angle from the
 * marker toward the star marker.  Orientation verified by unit tests via
 * bounding boxes (crescent hugs the star side, gibbous crosses the middle).
 */

export function markerRadius(angularDiameterDeg: number, maxDeg: number): number {
  const ratio = maxDeg > 0 ? Math.min(1.0, Math.max(0.0, angularDiameterDeg / maxDeg)) : 0
  return 2.5 + 11.5 * Math.sqrt(ratio)
}

/** Screen-space angle (SVG y-down math convention) from (cx, cy) toward the star. */
export function brightAngleRad(cx: number, cy: number, starX: number, starY: number): number {
  return Math.atan2(starY - cy, starX - cx)
}

/** SVG path of the illuminated region inside the circle (cx, cy, r). */
export function phasePathD(
  cx: number,
  cy: number,
  r: number,
  k: number,
  angleRad: number,
): string {
  const clamped = Math.min(1.0, Math.max(0.0, k))
  if (clamped >= 1.0) {
    return `M ${fmt(cx - r)} ${fmt(cy)} A ${fmt(r)} ${fmt(r)} 0 1 1 ${fmt(cx + r)} ${fmt(cy)} A ${fmt(r)} ${fmt(r)} 0 1 1 ${fmt(cx - r)} ${fmt(cy)} Z`
  }
  if (clamped <= 0.0) return ''
  const cos = Math.cos(angleRad)
  const sin = Math.sin(angleRad)
  // u points at the star; v is perpendicular; the terminator meets the limb
  // at c ± r·v (its semi-major axis is r along v).
  const p1x = cx - r * sin
  const p1y = cy + r * cos
  const p2x = cx + r * sin
  const p2y = cy - r * cos
  const b = r * Math.abs(2.0 * clamped - 1.0)
  const rot = fmt((angleRad * 180.0) / Math.PI)
  // Limb arc p1→p2 through the bright pole (screen-CCW ⇒ sweep 0); the
  // terminator bulges toward the star for a crescent (k<0.5), away for a
  // gibbous (k>0.5).  A zero-radius SVG arc renders as a line (half phase).
  const terminatorSweep = clamped < 0.5 ? 1 : 0
  return (
    `M ${fmt(p1x)} ${fmt(p1y)} ` +
    `A ${fmt(r)} ${fmt(r)} 0 0 0 ${fmt(p2x)} ${fmt(p2y)} ` +
    `A ${fmt(b)} ${fmt(r)} ${rot} 0 ${terminatorSweep} ${fmt(p1x)} ${fmt(p1y)} Z`
  )
}

function fmt(value: number): number {
  return Math.round(value * 1000) / 1000
}
