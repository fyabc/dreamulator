/**
 * MapViewer coordinate system — single source of truth for all geographic ↔ screen
 * transforms.  Replaces the fragile pan + panWrapOffset accumulation with a simple
 * mapCenter lon/lat model that wraps modulo 360°.
 *
 * ## Design
 *
 * The view state is defined by two values:
 *   mapCenter — longitude & latitude of the point displayed at the screen centre
 *   zoom      — positive scale factor (≥1)
 *
 * A higher zoom brings the camera closer (the map appears larger).  The camera
 * visible height at zoom=1 is 2*5*tan(25°) world units; at zoom it is divided by
 * zoom, so one screen pixel = constant / zoom world units.
 *
 * ## Horizontal wrapping
 *
 * mapCenter.lon is kept in [-180, 180].  When the user drags past ±180 the
 * value wraps with modulo, so it never grows without bound.
 *
 * ## Projection
 *
 * Currently hard-coded to equirectangular (the only projection used by the GPU
 * path).  Other projections can be added later via strategy injection.
 */

/** A geographic coordinate in degrees. */
export interface LonLat {
  lon: number
  lat: number
}

/** The view state that fully determines what the user sees. */
export interface MapViewState {
  mapCenter: LonLat
  zoom: number
}

/** Container pixel dimensions. */
export interface Viewport {
  width: number
  height: number
}

// ---------------------------------------------------------------------------
// Core transforms
// ---------------------------------------------------------------------------

/**
 * Forward projection: geographic → screen pixels.
 *
 * For equirectangular:
 *   screenX = (lon - centerLon) / 360 * vpWidth * zoom + vpWidth/2
 *   screenY = (centerLat - lat) / 180 * vpHeight * zoom + vpHeight/2
 *
 * Map wraps horizontally: a point at lon+360 maps to the same screenX as lon.
 */
export function lonLatToScreen(
  ll: LonLat,
  state: MapViewState,
  vp: Viewport,
): { x: number; y: number } {
  const dx = (((ll.lon - state.mapCenter.lon) % 360) + 540) % 360 - 180 // shortest delta in [-180, 180]
  const dy = state.mapCenter.lat - ll.lat
  const x = (dx / 360) * vp.width * state.zoom + vp.width / 2
  const y = (dy / 180) * vp.height * state.zoom + vp.height / 2
  return { x, y }
}

/**
 * Reverse projection: screen pixels → geographic.
 *
 * The returned longitude is always in [-180, 180].
 */
export function screenToLonLat(
  px: number,
  py: number,
  state: MapViewState,
  vp: Viewport,
): LonLat {
  const dx = (px - vp.width / 2) / (vp.width * state.zoom)
  const dy = (py - vp.height / 2) / (vp.height * state.zoom)
  let lon = state.mapCenter.lon + dx * 360
  let lat = state.mapCenter.lat - dy * 180

  // Wrap lon to [-180, 180]
  lon = ((lon + 180) % 360 + 360) % 360 - 180
  // Clamp lat to [-90, 90]
  lat = Math.max(-90, Math.min(90, lat))

  return { lon, lat }
}

// ---------------------------------------------------------------------------
// Drag / zoom helpers
// ---------------------------------------------------------------------------

/**
 * Apply a screen-pixel drag delta to the view state.
 * Positive delta.x → content moves right → mapCenter moves toward negative lon.
 */
export function applyDrag(
  state: MapViewState,
  deltaPx: { dx: number; dy: number },
  vp: Viewport,
): MapViewState {
  // dx>0 (drag right) → content moves right → centre moves toward -lon
  // dy>0 (drag down)  → content moves down  → centre moves toward +lat
  const dLon = -(deltaPx.dx / vp.width) * (360 / state.zoom)
  const dLat = (deltaPx.dy / vp.height) * (180 / state.zoom)
  let newLon = state.mapCenter.lon + dLon
  const newLat = state.mapCenter.lat + dLat

  // Wrap lon, clamp lat
  newLon = ((newLon + 180) % 360 + 360) % 360 - 180
  const clampedLat = Math.max(-90, Math.min(90, newLat))

  return {
    mapCenter: { lon: newLon, lat: clampedLat },
    zoom: state.zoom,
  }
}

/**
 * Zoom toward a screen point, keeping that geographic position fixed under the cursor.
 */
export function applyZoom(
  state: MapViewState,
  factor: number,
  anchorScreen: { x: number; y: number },
  vp: Viewport,
): MapViewState {
  const newZoom = state.zoom * factor

  // The anchor geographic point in the old state
  const anchorLL = screenToLonLat(anchorScreen.x, anchorScreen.y, state, vp)

  // In the new state (with newZoom), we want the same lon/lat at the anchor screen position.
  // Work backwards: the centre lon/lat that achieves this.
  const dx = (anchorScreen.x - vp.width / 2) / (vp.width * newZoom)
  const dy = (anchorScreen.y - vp.height / 2) / (vp.height * newZoom)
  let newLon = anchorLL.lon - dx * 360
  let newLat = anchorLL.lat + dy * 180

  newLon = ((newLon + 180) % 360 + 360) % 360 - 180
  newLat = Math.max(-90, Math.min(90, newLat))

  return {
    mapCenter: { lon: newLon, lat: newLat },
    zoom: newZoom,
  }
}

// ---------------------------------------------------------------------------
// Pixel ↔ elevation array helpers
// ---------------------------------------------------------------------------

/**
 * Convert lon/lat to pixel indices into the equirectangular elevation array.
 * Handles horizontal wrapping.  Returns null if lat is out of bounds.
 */
export function lonLatToPixel(
  ll: LonLat,
  mapW: number,
  mapH: number,
): { px: number; py: number } | null {
  if (ll.lat < -90 || ll.lat > 90) return null
  let wLon = ((ll.lon + 180) % 360 + 360) % 360
  let px = Math.floor((wLon / 360) * mapW) % mapW
  let py = Math.floor(((90 - ll.lat) / 180) * mapH)
  py = Math.max(0, Math.min(mapH - 1, py))
  return { px, py }
}

/**
 * Clamp a view state's zoom to the given range and its centre lat to [-90, 90].
 */
export function clampViewState(
  state: MapViewState,
  minZoom: number,
  maxZoom: number,
): MapViewState {
  return {
    mapCenter: {
      lon: ((state.mapCenter.lon + 180) % 360 + 360) % 360 - 180,
      lat: Math.max(-90, Math.min(90, state.mapCenter.lat)),
    },
    zoom: Math.max(minZoom, Math.min(maxZoom, state.zoom)),
  }
}
