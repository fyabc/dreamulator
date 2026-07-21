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
  voronoiCells,
  cvtMesh,
  hoveredCell,
  selectedCells,
}: MapSvgOverlayProps) {
  // Build vertex lookup from CVT mesh
  const vertexLookup = useMemo(() => {
    if (!cvtMesh) return null
    const map = new Map<number, { lon: number; lat: number }>()
    cvtMesh.vertices.forEach((v) => map.set(v.id, { lon: v.lon, lat: v.lat }))
    return map
  }, [cvtMesh])

  // Build region lookup from CVT mesh
  const regionByCell = useMemo(() => {
    if (!cvtMesh) return null
    const map = new Map<number, (typeof cvtMesh.regions)[0]>()
    cvtMesh.regions.forEach((r) => map.set(r.id, r))
    return map
  }, [cvtMesh])

  // Stroke width scales inversely with zoom
  const strokeWidth = Math.max(0.5, 1.5 / zoom)

  // Dynamic longitude offsets for seamless horizontal wrapping
  const wrapOffsets = useMemo(() => {
    const pLeft = project(-180, 0)
    const pRight = project(180, 0)
    const mapPxWidth = pRight.x - pLeft.x
    const centerPx = viewWidth / 2
    const lonAtCenter = mapPxWidth > 0
      ? -180 + ((centerPx - pLeft.x) / mapPxWidth) * 360
      : 0
    const centerOffset = Math.round(lonAtCenter / 360) * 360
    const extraCopies = Math.ceil(viewWidth / (mapPxWidth || 1)) + 1
    const result: number[] = []
    for (let i = -extraCopies; i <= extraCopies; i++) {
      result.push(centerOffset + i * 360)
    }
    return result
  }, [project, viewWidth])

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
        if (!region || !region.vertex_ids || region.vertex_ids.length < 3) return []

        const polygons: React.ReactNode[] = []
        for (const offset of wrapOffsets) {
          const projectedPoints = region.vertex_ids
            .map((vid) => {
              const v = vertexLookup.get(vid)
              if (!v) return null
              return project(v.lon + offset, v.lat)
            })
            .filter((p): p is { x: number; y: number } => p !== null)

          if (projectedPoints.length < 3) continue

          // Viewport culling
          const minX = Math.min(...projectedPoints.map((p) => p.x))
          const maxX = Math.max(...projectedPoints.map((p) => p.x))
          const minY = Math.min(...projectedPoints.map((p) => p.y))
          const maxY = Math.max(...projectedPoints.map((p) => p.y))
          if (maxX < -20 || minX > viewWidth + 20 || maxY < -20 || minY > viewHeight + 20) continue
          if (maxX - minX > viewWidth * 0.8) continue

          const pointsStr = projectedPoints.map((p) => `${p.x},${p.y}`).join(' ')

          polygons.push(
            <polygon
              key={`${cell.id}_${offset}`}
              points={pointsStr}
              fill={isSelected ? 'rgba(255,255,0,0.1)' : 'rgba(0,255,255,0.08)'}
              stroke={isSelected ? '#ff0' : '#0ff'}
              strokeWidth={isSelected ? strokeWidth * 2.5 : strokeWidth * 2}
              strokeOpacity={isSelected ? 1 : 0.8}
            />,
          )
        }
        return polygons
      })
    }

    // Fallback: circles at cell centers
    return voronoiCells.flatMap((cell) => {
      const isHovered = hoveredCell === cell.id
      const isSelected = selectedCells.has(cell.id)
      if (!isHovered && !isSelected) return []

      const circles: React.ReactNode[] = []
      for (const offset of wrapOffsets) {
        const p = project(cell.lon + offset, cell.lat)
        if (p.x < -20 || p.x > viewWidth + 20 || p.y < -20 || p.y > viewHeight + 20) continue

        circles.push(
          <circle
            key={`${cell.id}_${offset}`}
            cx={p.x}
            cy={p.y}
            r={Math.max(3, 6 / zoom)}
            fill={isSelected ? 'rgba(255,255,0,0.15)' : 'rgba(0,255,255,0.1)'}
            stroke={isSelected ? '#ff0' : '#0ff'}
            strokeWidth={isSelected ? strokeWidth * 2.5 : strokeWidth * 2}
            strokeOpacity={isSelected ? 1 : 0.8}
          />,
        )
      }
      return circles
    })
  }, [
    voronoiCells, project, zoom, viewWidth, viewHeight, wrapOffsets,
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
