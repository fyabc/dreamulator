/** panProjector — perspective (gnomonic) projection for the look-around view
 *  (the Stellarium posture): a view direction (azimuth + altitude) and a
 *  horizontal field of view.  Positions come from the engine result already
 *  in hand, so looking around is pure client-side geometry — no fetch.
 *
 *  Camera basis: forward = ENU direction of the view centre; right = forward
 *  crossed with the world up (analytic pole limit keeps straight-up views
 *  stable, roll defined by azimuth — the planetarium convention); up
 *  completes the frame.  Screen: x grows right (east when facing north),
 *  y grows down (zenith up), focal = (width/2) / tan(fov/2).
 */

const DEG = Math.PI / 180

export interface Vec3 {
  /** east */
  e: number
  /** north */
  n: number
  /** up */
  u: number
}

export interface LookDirection {
  azDeg: number
  altDeg: number
  /** vertical field of view in degrees (Stellarium's convention — landscape
   *  and portrait viewports both keep sane edge distortion) */
  fovDeg: number
}

export const PAN_FOV_LIMITS = { min: 15, max: 120 }
/** Keeps cos(alt) clear of zero: the pole itself has no unique roll. */
export const PAN_ALT_LIMIT = 89.5
/** Directions closer to the view plane than this are treated as behind. */
const NEAR_Z = 0.02

export interface ScreenPoint {
  x: number
  y: number
}

export function wrapAzimuth(deg: number): number {
  return ((deg % 360) + 360) % 360
}

export function clampLook(look: LookDirection): LookDirection {
  return {
    azDeg: wrapAzimuth(look.azDeg),
    altDeg: Math.max(-PAN_ALT_LIMIT, Math.min(PAN_ALT_LIMIT, look.altDeg)),
    fovDeg: Math.max(PAN_FOV_LIMITS.min, Math.min(PAN_FOV_LIMITS.max, look.fovDeg)),
  }
}

export function enuFromAltAz(altDeg: number, azDeg: number): Vec3 {
  const alt = altDeg * DEG
  const az = azDeg * DEG
  return { e: Math.cos(alt) * Math.sin(az), n: Math.cos(alt) * Math.cos(az), u: Math.sin(alt) }
}

/** Inverse of enuFromAltAz (azimuth wrapped to [0, 360)). */
export function altAzFromDir(v: Vec3): { altDeg: number; azDeg: number } {
  const alt = Math.asin(Math.max(-1, Math.min(1, v.u))) / DEG
  return { altDeg: alt, azDeg: wrapAzimuth(Math.atan2(v.e, v.n) / DEG) }
}

function dot(a: Vec3, b: Vec3): number {
  return a.e * b.e + a.n * b.n + a.u * b.u
}

function cross(a: Vec3, b: Vec3): Vec3 {
  return {
    e: a.n * b.u - a.u * b.n,
    n: a.u * b.e - a.e * b.u,
    u: a.e * b.n - a.n * b.e,
  }
}

export interface LookBasis {
  forward: Vec3
  right: Vec3
  up: Vec3
}

export function lookBasis(azDeg: number, altDeg: number): LookBasis {
  const forward = enuFromAltAz(altDeg, azDeg)
  // right ∝ forward × worldUp = (cos alt · cos az, −cos alt · sin az, 0);
  // at the poles cos alt → 0, so take the analytic limit (cos az, −sin az, 0).
  const ca = Math.cos(azDeg * DEG)
  const sa = Math.sin(azDeg * DEG)
  const right: Vec3 = { e: ca, n: -sa, u: 0 }
  return { forward, right, up: cross(right, forward) }
}

export interface PanProjector {
  width: number
  height: number
  look: LookDirection
  /** Project a direction; null when behind or grazing the view plane. */
  projectDir(v: Vec3): ScreenPoint | null
  projectAltAz(altDeg: number, azDeg: number): ScreenPoint | null
  /**
   * Ground-polygon helper: like projectDir, but points behind the view plane
   * are pushed to the near plane — they land far off-screen in the correct
   * direction, keeping the horizon polygon connected.
   */
  projectDirClamped(v: Vec3): ScreenPoint
  /** Vertical degrees per screen pixel at the view centre (drag scale, isotropic). */
  degPerPixelY(): number
}

export function panProjector(width: number, height: number, look: LookDirection): PanProjector {
  const basis = lookBasis(look.azDeg, look.altDeg)
  const focal = (height / 2) / Math.tan((look.fovDeg / 2) * DEG)
  const toScreen = (v: Vec3, cz: number): ScreenPoint => ({
    x: width / 2 + (dot(v, basis.right) / cz) * focal,
    y: height / 2 - (dot(v, basis.up) / cz) * focal,
  })
  return {
    width,
    height,
    look,
    projectDir(v: Vec3): ScreenPoint | null {
      const cz = dot(v, basis.forward)
      return cz > NEAR_Z ? toScreen(v, cz) : null
    },
    projectAltAz(altDeg: number, azDeg: number): ScreenPoint | null {
      return this.projectDir(enuFromAltAz(altDeg, azDeg))
    },
    projectDirClamped(v: Vec3): ScreenPoint {
      return toScreen(v, Math.max(dot(v, basis.forward), NEAR_Z))
    },
    degPerPixelY(): number {
      return look.fovDeg / height
    },
  }
}

/**
 * Ground fill as an SVG path: the horizon arc in front of the camera (the
 * sweep is centred on the view azimuth so the front arc is contiguous in
 * sample order), closed through the nadir so the region below the horizon is
 * covered however far down the camera looks.  Empty string when the horizon
 * is entirely behind/near-grazing (looking steeply up).
 */
export function groundPath(projector: PanProjector, samples = 121): string {
  const pts: ScreenPoint[] = []
  for (let i = 0; i <= samples; i++) {
    const az = projector.look.azDeg - 180 + (i / samples) * 360
    const p = projector.projectDir(enuFromAltAz(0, az))
    if (p) pts.push(p)
  }
  if (pts.length < 2) return ''
  const nadir = projector.projectDirClamped({ e: 0, n: 0, u: -1 })
  const d = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
  d.push(`L ${nadir.x.toFixed(1)} ${nadir.y.toFixed(1)} Z`)
  return d.join(' ')
}

/** Horizon stroke as an SVG path (the same front arc, unclosed). */
export function horizonPath(projector: PanProjector, samples = 121): string {
  const pts: ScreenPoint[] = []
  for (let i = 0; i <= samples; i++) {
    const az = projector.look.azDeg - 180 + (i / samples) * 360
    const p = projector.projectDir(enuFromAltAz(0, az))
    if (p) pts.push(p)
  }
  if (pts.length < 2) return ''
  return pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ')
}

/**
 * Pointer-drag mapping (grab-the-sky): dragging right moves the sky right,
 * so the view turns toward smaller azimuth; dragging down pulls the sky down
 * and the view climbs.  Returns the clamped new look.
 */
export function lookFromDrag(
  start: LookDirection,
  startPx: ScreenPoint,
  currentPx: ScreenPoint,
  degPerPx: number,
): LookDirection {
  return clampLook({
    azDeg: start.azDeg - (currentPx.x - startPx.x) * degPerPx,
    altDeg: start.altDeg + (currentPx.y - startPx.y) * degPerPx,
    fovDeg: start.fovDeg,
  })
}

/** Pinch zoom: spreading fingers zooms in (smaller field). */
export function fovFromPinch(startFov: number, startDist: number, currentDist: number): number {
  if (currentDist <= 0) return startFov
  return Math.max(PAN_FOV_LIMITS.min, Math.min(PAN_FOV_LIMITS.max, startFov * (startDist / currentDist)))
}
