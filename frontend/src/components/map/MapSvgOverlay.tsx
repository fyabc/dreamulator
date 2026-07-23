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
    cvtMesh.vertices.forEach(([x, y, z], idx) => {
      const lat = Math.asin(y) * (180 / Math.PI)
      const lon = Math.atan2(z, x) * (180 / Math.PI)
      map.set(idx, { lon, lat })
    })
    return map
  }, [cvtMesh])

  // Build region lookup from CVT mesh: cellId → vertex index array
  const regionByCell = useMemo(() => {
    if (!cvtMesh) return null
    const map = new Map<number, number[]>()
    cvtMesh.regions.forEach((region, cellId) => {
      map.set(cellId, region)
    })
    return map
  }, [cvtMesh])

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
            fill={isSelected ? 'rgba(255,255,0,0.1)' : 'rgba(0,255,255,0.08)'}
            stroke={isSelected ? '#ff0' : '#0ff'}
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
          fill={isSelected ? 'rgba(255,255,0,0.15)' : 'rgba(0,255,255,0.1)'}
          stroke={isSelected ? '#ff0' : '#0ff'}
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
      <g className="pointer-events-none">{highlightElements}</g>
    </svg>
  )
}
