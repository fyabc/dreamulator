/**
 * MapSvgOverlay — SVG layer rendered on top of the Three.js terrain canvas.
 *
 * Renders Voronoi cells, plate boundaries, rivers, and labels as SVG
 * elements.  Coordinates are transformed from (lon, lat) to viewport
 * pixels using the current camera transform.
 */

import { useMemo } from 'react'
import type { VoronoiCell, TectonicPlate, MapFeature } from '../../viewers/map/types'
import { plateColor } from '../../viewers/map/utils/colorScales'

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
  plates: TectonicPlate[]
  features: MapFeature[]

  // Visibility
  showVoronoi: boolean
  showPlates: boolean
  showFeatures: boolean

  // Interaction
  hoveredCell: number | null
  selectedCells: Set<number>
  onCellHover: (cellId: number | null) => void
  onCellClick: (cellId: number, shiftKey: boolean) => void

  // Color cells by plate?
  colorByPlate: boolean
}

export default function MapSvgOverlay({
  viewWidth,
  viewHeight,
  project,
  zoom,
  voronoiCells,
  plates,
  features,
  showVoronoi,
  showPlates,
  showFeatures,
  hoveredCell,
  selectedCells,
  onCellHover,
  onCellClick,
  colorByPlate,
}: MapSvgOverlayProps) {
  // Build plate lookup
  const plateByCell = useMemo(() => {
    const map = new Map<number, { id: string; index: number }>()
    plates.forEach((plate, idx) => {
      plate.cell_ids.forEach((cid) => map.set(cid, { id: plate.id, index: idx }))
    })
    return map
  }, [plates])

  // Stroke width scales inversely with zoom
  const strokeWidth = Math.max(0.5, 1.5 / zoom)

  // Dynamic longitude offsets for seamless horizontal wrapping (handles unlimited panning)
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

  // Project features to SVG paths
  const featurePaths = useMemo(() => {
    if (!showFeatures) return []
    return features.map((feat) => {
      const points = feat.coordinates.map(([lon, lat]) => {
        const p = project(lon, lat)
        return `${p.x},${p.y}`
      })
      return {
        id: feat.id,
        type: feat.type,
        d: `M${points.join('L')}`,
      }
    })
  }, [features, showFeatures, project])

  // For Voronoi cells, we render as circles at cell centers (simplified —
  // full polygon rendering would need the Voronoi tessellation computed
  // on the frontend, which is a Phase 2 feature)
  const cellElements = useMemo(() => {
    if (!showVoronoi && !colorByPlate) return null

    return voronoiCells.flatMap((cell) => {
      const plateInfo = plateByCell.get(cell.id)
      const isHovered = hoveredCell === cell.id
      const isSelected = selectedCells.has(cell.id)

      let fill = 'transparent'
      if (colorByPlate && plateInfo) {
        fill = plateColor(plateInfo.index)
      }

      const circles: React.ReactNode[] = []
      for (const offset of wrapOffsets) {
        const p = project(cell.lon + offset, cell.lat)
        if (p.x < -20 || p.x > viewWidth + 20 || p.y < -20 || p.y > viewHeight + 20) continue

        circles.push(
          <circle
            key={`${cell.id}_${offset}`}
            cx={p.x}
            cy={p.y}
            r={Math.max(2, 4 / zoom)}
            fill={fill}
            fillOpacity={colorByPlate ? 0.3 : 0}
            stroke={isSelected ? '#ff0' : isHovered ? '#0ff' : colorByPlate ? fill : '#666'}
            strokeWidth={isSelected || isHovered ? strokeWidth * 2 : strokeWidth}
            strokeOpacity={isSelected ? 1 : isHovered ? 0.8 : 0.3}
            style={{ cursor: 'pointer' }}
            onMouseEnter={() => onCellHover(cell.id)}
            onMouseLeave={() => onCellHover(null)}
            onClick={(e) => onCellClick(cell.id, e.shiftKey)}
          />,
        )
      }
      return circles
    })
  }, [
    voronoiCells, project, zoom, viewWidth, viewHeight, wrapOffsets,
    plateByCell, colorByPlate, showVoronoi,
    hoveredCell, selectedCells, onCellHover, onCellClick, strokeWidth,
  ])

  // Plate boundary outlines (simplified: draw lines between cells of different plates)
  const plateBoundaries = useMemo(() => {
    if (!showPlates || plates.length === 0) return null

    // Collect raw boundary segments as (lon, lat) pairs
    const rawSegments: { lon1: number; lat1: number; lon2: number; lat2: number }[] = []
    voronoiCells.forEach((cell) => {
      const myPlate = plateByCell.get(cell.id)?.id
      cell.neighbors.forEach((nbId) => {
        if (nbId > cell.id) {
          const nbPlate = plateByCell.get(nbId)?.id
          if (myPlate && nbPlate && myPlate !== nbPlate) {
            const nb = voronoiCells[nbId]
            if (nb) {
              // Skip segments that cross the antimeridian or span unrealistic latitude ranges
              // (Voronoi neighbors at lon ≈ ±180° can be pole-to-pole apart in equirectangular projection)
              if (Math.abs(cell.lon - nb.lon) > 180) return
              if (Math.abs(cell.lat - nb.lat) > 20) return
              rawSegments.push({
                lon1: cell.lon, lat1: cell.lat,
                lon2: nb.lon, lat2: nb.lat,
              })
            }
          }
        }
      })
    })

    // Map width in screen pixels (for culling stretched wrap-around segments)
    const mapScreenWidth = Math.abs(project(180, 0).x - project(-180, 0).x)

    // Render each segment at dynamic longitude offsets for seamless wrapping
    const lines: React.ReactNode[] = []
    let idx = 0
    for (const seg of rawSegments) {
      for (const offset of wrapOffsets) {
        const p1 = project(seg.lon1 + offset, seg.lat1)
        const p2 = project(seg.lon2 + offset, seg.lat2)
        // Skip segments that span more than half the map width (wrap-around artifacts)
        if (Math.abs(p1.x - p2.x) > mapScreenWidth * 0.5) continue
        // Cull segments fully outside viewport
        if (p1.x < -50 && p2.x < -50) continue
        if (p1.x > viewWidth + 50 && p2.x > viewWidth + 50) continue
        if (p1.y < -50 && p2.y < -50) continue
        if (p1.y > viewHeight + 50 && p2.y > viewHeight + 50) continue

        lines.push(
          <line
            key={`pb-${idx++}`}
            x1={p1.x}
            y1={p1.y}
            x2={p2.x}
            y2={p2.y}
            stroke="#e63946"
            strokeWidth={strokeWidth * 2}
            strokeOpacity={0.7}
            strokeLinecap="round"
          />,
        )
      }
    }

    return lines
  }, [voronoiCells, plates, plateByCell, showPlates, project, strokeWidth, wrapOffsets])

  return (
    <svg
      className="absolute inset-0 pointer-events-none"
      width={viewWidth}
      height={viewHeight}
      style={{ zIndex: 10 }}
    >
      {/* Plate boundaries */}
      <g className="pointer-events-none">{plateBoundaries}</g>

      {/* Features (rivers, ridges) */}
      <g className="pointer-events-none">
        {featurePaths.map((fp) => (
          <path
            key={fp.id}
            d={fp.d}
            fill="none"
            stroke={fp.type === 'river' ? '#4dabf7' : fp.type === 'ridge' ? '#e8590c' : '#adb5bd'}
            strokeWidth={strokeWidth * 1.5}
            strokeOpacity={0.6}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
      </g>

      {/* Voronoi cells (interactive — needs pointer events) */}
      <g className="pointer-events-auto">{cellElements}</g>
    </svg>
  )
}
