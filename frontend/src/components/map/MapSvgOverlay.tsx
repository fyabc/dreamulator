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
    const SAMPLE = 2  // degrees between samples along a line
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

  return (
    <svg
      className="absolute inset-0 pointer-events-none"
      width={viewWidth}
      height={viewHeight}
      style={{ zIndex: 10 }}
    >
      <g className="pointer-events-none">{graticuleElements}</g>
      <g className="pointer-events-none">{highlightElements}</g>
    </svg>
  )
}
