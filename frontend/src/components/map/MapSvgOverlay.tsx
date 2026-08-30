/**
 * MapSvgOverlay — visual-only SVG layer on top of the Three.js terrain.
 *
 * Renders hover/selection highlights for Voronoi cells.
 * Hit-testing is done mathematically via KD-tree in MapViewer (not via SVG polygons).
 */

import { useMemo } from 'react'
import type {
  VoronoiCell,
  CVTMesh,
} from '../../viewers/map/types'

interface MapSvgOverlayProps {
  /** SVG viewport width in CSS pixels. */
  viewWidth: number
  /** SVG viewport height in CSS pixels. */
  viewHeight: number
  /** Transform from map coords to viewport: { x: px, y: py } for a given (lon, lat). */
  project: (lon: number, lat: number) => { x: number; y: number }
  /** Current zoom level (for stroke width scaling). */
  zoom: number
  /** Cumulative longitude offset from horizontal wrapping (degrees). */
  panWrapOffset: number

  // Data
  voronoiCells: VoronoiCell[]
  /** CVT mesh data for polygon rendering (optional). */
  cvtMesh?: CVTMesh | null

  // Visual state (read-only — no event handlers)
  hoveredCell: number | null
  selectedCells: Set<number>

  /** Ocean current arrow opacity (0 = hidden). */
  currentOpacity?: number
  /** Wind arrow opacity (0 = hidden). */
  windOpacity?: number
  /** Monthly wind (tech debt 24): N×12 east/north components in mesh-cell
   *  order.  When both are provided the arrows show month `month` instead of
   *  the annual-mean wind. */
  monthlyWindEast?: Float32Array | null
  monthlyWindNorth?: Float32Array | null
  month?: number

}

export default function MapSvgOverlay({
  viewWidth,
  viewHeight,
  project,
  zoom,
  panWrapOffset,
  voronoiCells,
  cvtMesh,
  hoveredCell,
  selectedCells,
  currentOpacity = 0,
  windOpacity = 0,
  monthlyWindEast = null,
  monthlyWindNorth = null,
  month = 0,
}: MapSvgOverlayProps) {
  // Build vertex lookup from CVT mesh: vertex idx → {lon, lat}
  const vertexLookup = useMemo(() => {
    if (!cvtMesh) return null
    const map = new Map<number, { lon: number; lat: number }>()
    for (const v of cvtMesh.vertices) {
      map.set(v.id, { lon: v.lon, lat: v.lat })
    }
    return map
  }, [cvtMesh])

  // Build region lookup from CVT mesh: cellId → vertex index array
  const regionByCell = useMemo(() => {
    if (!cvtMesh) return null
    const map = new Map<number, number[]>()
    for (const r of cvtMesh.regions) {
      map.set(r.id, r.vertex_ids)
    }
    return map
  }, [cvtMesh])

  // Graticule: lat/lon grid lines drawn as polylines via project().  Straight for
  // equirectangular, smooth curves for Mollweide/Robinson (this replaces the old
  // texture-baked grid, which warped coarsely when reprojected).  Rendered under
  // the cell highlights.  Recomputes only when `project` changes (pan/zoom/resize).
  const graticuleElements = useMemo(() => {
    const STEP = 30   // degrees between grid lines
    const SAMPLE = 5  // degrees between samples (visual difference ≤2° is imperceptible)
    const lines: JSX.Element[] = []
    // Latitude lines (constant lat, sample lon)
    for (let lat = -90 + STEP; lat < 90; lat += STEP) {
      const pts: string[] = []
      for (let lon = -180; lon <= 180; lon += SAMPLE) {
        const p = project(lon, lat)
        pts.push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`)
      }
      lines.push(
        <polyline key={`lat${lat}`} points={pts.join(' ')} fill="none"
          stroke="rgba(255,255,255,0.16)" strokeWidth={1} />,
      )
    }
    // Longitude lines (constant lon, sample lat)
    for (let lon = -180 + STEP; lon < 180; lon += STEP) {
      const pts: string[] = []
      for (let lat = -90; lat <= 90; lat += SAMPLE) {
        const p = project(lon, lat)
        pts.push(`${p.x.toFixed(1)},${p.y.toFixed(1)}`)
      }
      lines.push(
        <polyline key={`lon${lon}`} points={pts.join(' ')} fill="none"
          stroke="rgba(255,255,255,0.16)" strokeWidth={1} />,
      )
    }
    return lines
  }, [project])

  // Stroke width scales inversely with zoom
  const strokeWidth = Math.max(0.5, 1.5 / zoom)

  // Unified wrap offset: -panWrapOffset cancels unwrappedPanX in project(),
  // leaving only pan.x (wrapped). Keeps highlights on-screen at any pan distance.
  const wrapOffset = -panWrapOffset

  // Visual highlights for hovered/selected cells ONLY (no hit-test, no events)
  const highlightElements = useMemo(() => {
    const shouldRender = hoveredCell !== null || selectedCells.size > 0
    if (!shouldRender) return null

    // Polygon rendering when CVT mesh is available
    if (vertexLookup && regionByCell) {
      return voronoiCells.flatMap((cell) => {
        const isHovered = hoveredCell === cell.id
        const isSelected = selectedCells.has(cell.id)
        if (!isHovered && !isSelected) return []

        const region = regionByCell.get(cell.id)
        if (!region || region.length < 3) return []

        const offset = wrapOffset
        const projectedPoints = region
          .map((vid: number) => {
            const v = vertexLookup.get(vid)
            if (!v) return null
            return project(v.lon + offset, v.lat)
          })
          .filter((p: { x: number; y: number } | null): p is { x: number; y: number } => p !== null)

        if (projectedPoints.length < 3) return []

        // Viewport culling
        const minX = Math.min(...projectedPoints.map((p: { x: number; y: number }) => p.x))
        const maxX = Math.max(...projectedPoints.map((p: { x: number; y: number }) => p.x))
        const minY = Math.min(...projectedPoints.map((p: { x: number; y: number }) => p.y))
        const maxY = Math.max(...projectedPoints.map((p: { x: number; y: number }) => p.y))
        if (maxX < -20 || minX > viewWidth + 20 || maxY < -20 || minY > viewHeight + 20) return []
        if (maxX - minX > viewWidth * 0.8) return []

        const pointsStr = projectedPoints.map((p) => `${p.x},${p.y}`).join(' ')

        return (
          <polygon
            key={cell.id}
            points={pointsStr}
            fill={isSelected ? 'rgba(255,220,50,0.15)' : 'rgba(40,120,255,0.15)'}
            stroke={isSelected ? '#ffdc32' : '#2878ff'}
            strokeWidth={isSelected ? strokeWidth * 2.5 : strokeWidth * 2}
            strokeOpacity={isSelected ? 1 : 0.8}
          />
        )
      })
    }

    // Fallback: circles at cell centers
    return voronoiCells.flatMap((cell) => {
      const isHovered = hoveredCell === cell.id
      const isSelected = selectedCells.has(cell.id)
      if (!isHovered && !isSelected) return []

      const offset = wrapOffset
      const p = project(cell.lon + offset, cell.lat)
      if (p.x < -20 || p.x > viewWidth + 20 || p.y < -20 || p.y > viewHeight + 20) return []

      return (
        <circle
          key={cell.id}
          cx={p.x}
          cy={p.y}
          r={Math.max(3, 6 / zoom)}
          fill={isSelected ? 'rgba(255,220,50,0.2)' : 'rgba(40,120,255,0.15)'}
          stroke={isSelected ? '#ffdc32' : '#2878ff'}
          strokeWidth={isSelected ? strokeWidth * 2.5 : strokeWidth * 2}
          strokeOpacity={isSelected ? 1 : 0.8}
        />
      )
    })
  }, [
    voronoiCells, project, zoom, viewWidth, viewHeight, wrapOffset,
    hoveredCell, selectedCells, strokeWidth, vertexLookup, regionByCell,
  ])

  // Ocean current arrows — per-cell stride sampling, filtered.
  const currentArrowElements = useMemo(() => {
    if (currentOpacity <= 0 || voronoiCells.length === 0) return null

    // Collect ocean cells with current data, compute max speed
    type OceanCell = { lon: number; lat: number; u: number; v: number; sstAnom: number }
    const oceanCells: OceanCell[] = []
    let maxSpd = 0
    for (const c of voronoiCells) {
      const u = c.ocean_current_east_m_s
      const v = c.ocean_current_north_m_s
      if (u == null || v == null) continue
      const s = Math.sqrt(u * u + v * v)
      if (s > maxSpd) maxSpd = s
      oceanCells.push({
        lon: c.lon ?? 0, lat: c.lat ?? 0,
        u, v, sstAnom: c.sst_anomaly_c ?? 0,
      })
    }
    if (oceanCells.length === 0 || maxSpd < 1e-9) return null

    // Fixed lat/lon grid — uniform spatial density, textbook quiver-plot look
    const gridStep = 4.5  // degrees
    const arrowScale = 1.0  // fixed pixel size, no zoom scaling
    const elements: JSX.Element[] = []

    // 2°-bin spatial index → fastest ocean cell in each bin
    const bins = new Map<string, number>()
    for (let i = 0; i < oceanCells.length; i++) {
      const oc = oceanCells[i]
      const blon = Math.round(oc.lon / 2) * 2
      const blat = Math.round(oc.lat / 2) * 2
      const key = `${blon},${blat}`
      const prev = bins.get(key)
      if (prev === undefined) { bins.set(key, i) }
      else {
        const ps = Math.sqrt(oceanCells[prev].u ** 2 + oceanCells[prev].v ** 2)
        if (Math.sqrt(oc.u ** 2 + oc.v ** 2) > ps) bins.set(key, i)
      }
    }

    for (let lat = -90 + gridStep; lat < 90; lat += gridStep) {
      for (let lon = -180 + gridStep; lon < 180; lon += gridStep) {
        const key = `${Math.round(lon / 2) * 2},${Math.round(lat / 2) * 2}`
        const idx = bins.get(key)
        if (idx === undefined) continue
        const oc = oceanCells[idx]
        const speed = Math.sqrt(oc.u * oc.u + oc.v * oc.v)
        if (speed < 1e-9) continue  // skip only truly still water

      const angle = Math.atan2(oc.v, oc.u)  // flow direction (radians)

      const p = project(oc.lon, oc.lat)
      if (p.x < -80 || p.x > viewWidth + 80 || p.y < -80 || p.y > viewHeight + 80) continue

      // Arrow geometry — sqrt stretch, scales with zoom, ~original size at 1x
      const speedFrac = Math.min(speed / maxSpd, 1.0)
      const len = Math.min(
        (1.5 + 13.5 * Math.sqrt(speedFrac)) * zoom * arrowScale,
        50,
      )
      const tipX = p.x + Math.cos(angle) * len
      const tipY = p.y - Math.sin(angle) * len  // SVG y down

      // Colour
      const warm = oc.sstAnom > 0
      const color = warm ? '#e040fb' : '#00bcd4'
      const strokeW = Math.max(0.8, len * 0.13)  // shaft ~13% of length
      const headLen = len * 0.38  // arrowhead ~38% of length
      const ha = 0.45  // ~26° half-angle (radians)

      // Shaft: ends BEFORE the tip so arrowhead is clearly visible
      const shaftEndX = tipX - Math.cos(angle) * headLen * 0.5
      const shaftEndY = tipY + Math.sin(angle) * headLen * 0.5
      const shaftStartX = p.x - Math.cos(angle) * len * 0.3
      const shaftStartY = p.y + Math.sin(angle) * len * 0.3
      elements.push(
        <line key={`shaft-${oc.lon}-${oc.lat}`}
          x1={shaftStartX} y1={shaftStartY} x2={shaftEndX} y2={shaftEndY}
          stroke={color} strokeWidth={strokeW} strokeLinecap="round"
          opacity={0.8} />,
      )

      // Arrowhead: filled triangle at the tip
      const hx1 = tipX - Math.cos(angle - ha) * headLen
      const hy1 = tipY + Math.sin(angle - ha) * headLen
      const hx2 = tipX - Math.cos(angle + ha) * headLen
      const hy2 = tipY + Math.sin(angle + ha) * headLen
      elements.push(
        <polygon key={`head-${oc.lon}-${oc.lat}`}
          points={`${tipX},${tipY} ${hx1.toFixed(1)},${hy1.toFixed(1)} ${hx2.toFixed(1)},${hy2.toFixed(1)}`}
          fill={color} stroke="none" opacity={0.85} />,
      )
    }
    }

    return (
      <g className="pointer-events-none" opacity={currentOpacity}>
        {elements}
      </g>
    )
  }, [currentOpacity, voronoiCells, project, viewWidth, viewHeight, zoom])

  // Wind arrows — identical algorithm, wind_east_m_s / wind_north_m_s fields
  const windArrowElements = useMemo(() => {
    if (windOpacity <= 0 || voronoiCells.length === 0) return null

    type WCell = { lon: number; lat: number; u: number; v: number; speed: number; tC: number }
    const wcells: WCell[] = []
    let maxSpd = 0
    const useMonthly = !!(monthlyWindEast && monthlyWindNorth)
    for (let i = 0; i < voronoiCells.length; i++) {
      const c = voronoiCells[i]
      let u: number, v: number
      if (useMonthly) {
        u = (monthlyWindEast as Float32Array)[i * 12 + month]
        v = (monthlyWindNorth as Float32Array)[i * 12 + month]
      } else {
        u = c.wind_east_m_s as number
        v = c.wind_north_m_s as number
      }
      if (u == null || v == null || !Number.isFinite(u) || !Number.isFinite(v)) continue
      const s = Math.sqrt(u * u + v * v)
      if (s > maxSpd) maxSpd = s
      wcells.push({ lon: c.lon ?? 0, lat: c.lat ?? 0, u, v, speed: s, tC: c.temperature_C ?? 0 })
    }
    if (wcells.length === 0 || maxSpd < 1e-9) return null

    const gridStep = 4.5
    const elements: JSX.Element[] = []

    const bins = new Map<string, number>()
    for (let i = 0; i < wcells.length; i++) {
      const wc = wcells[i]
      const blon = Math.round(wc.lon / 2) * 2
      const blat = Math.round(wc.lat / 2) * 2
      const key = `${blon},${blat}`
      const prev = bins.get(key)
      if (prev === undefined) { bins.set(key, i) }
      else if (wc.speed > wcells[prev].speed) bins.set(key, i)
    }

    for (let lat = -90 + gridStep; lat < 90; lat += gridStep) {
      for (let lon = -180 + gridStep; lon < 180; lon += gridStep) {
        const key = `${Math.round(lon / 2) * 2},${Math.round(lat / 2) * 2}`
        const idx = bins.get(key)
        if (idx === undefined) continue
        const wc = wcells[idx]
        if (wc.speed < 1e-9) continue

        const angle = Math.atan2(wc.v, wc.u)
        const p = project(wc.lon, wc.lat)
        if (p.x < -80 || p.x > viewWidth + 80 || p.y < -80 || p.y > viewHeight + 80) continue

        const speedFrac = Math.min(wc.speed / maxSpd, 1.0)
        const len = Math.min((1.0 + 8.0 * Math.sqrt(speedFrac)) * zoom, 40)
        const tipX = p.x + Math.cos(angle) * len
        const tipY = p.y - Math.sin(angle) * len

        // Temperature-based colour: blue(cold, -10°C) → green → red(warm, +25°C)
        const tClamped = Math.min(Math.max(wc.tC, -10), 25)
        const h = 240 - (tClamped + 10) * (240 / 35)
        const color = `hsl(${h}, 70%, 50%)`
        const strokeW = Math.max(0.8, len * 0.13)
        const headLen = len * 0.38
        const ha = 0.45

        const shaftEndX = tipX - Math.cos(angle) * headLen * 0.5
        const shaftEndY = tipY + Math.sin(angle) * headLen * 0.5
        const shaftStartX = p.x - Math.cos(angle) * len * 0.3
        const shaftStartY = p.y + Math.sin(angle) * len * 0.3
        elements.push(
          <line key={`wshaft-${wc.lon}-${wc.lat}`}
            x1={shaftStartX} y1={shaftStartY} x2={shaftEndX} y2={shaftEndY}
            stroke={color} strokeWidth={strokeW} strokeLinecap="round"
            opacity={0.8} />,
        )
        const hx1 = tipX - Math.cos(angle - ha) * headLen
        const hy1 = tipY + Math.sin(angle - ha) * headLen
        const hx2 = tipX - Math.cos(angle + ha) * headLen
        const hy2 = tipY + Math.sin(angle + ha) * headLen
        elements.push(
          <polygon key={`whead-${wc.lon}-${wc.lat}`}
            points={`${tipX},${tipY} ${hx1.toFixed(1)},${hy1.toFixed(1)} ${hx2.toFixed(1)},${hy2.toFixed(1)}`}
            fill={color} stroke="none" opacity={0.85} />,
        )
      }
    }

    return (
      <g className="pointer-events-none" opacity={windOpacity}>
        {elements}
      </g>
    )
  }, [windOpacity, voronoiCells, project, viewWidth, viewHeight, zoom, monthlyWindEast, monthlyWindNorth, month])

  return (
    <svg
      className="absolute inset-0 pointer-events-none"
      width={viewWidth}
      height={viewHeight}
      style={{ zIndex: 10 }}
    >
      <g className="pointer-events-none">{graticuleElements}</g>
      <g className="pointer-events-none">{currentArrowElements}</g>
      <g className="pointer-events-none">{windArrowElements}</g>
      <g className="pointer-events-none">{highlightElements}</g>
    </svg>
  )
}
