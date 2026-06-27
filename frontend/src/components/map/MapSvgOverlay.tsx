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

    return voronoiCells.map((cell) => {
      const p = project(cell.lon, cell.lat)
      if (p.x < -20 || p.x > viewWidth + 20 || p.y < -20 || p.y > viewHeight + 20) return null

      const plateInfo = plateByCell.get(cell.id)
      const isHovered = hoveredCell === cell.id
      const isSelected = selectedCells.has(cell.id)

      let fill = 'transparent'
      if (colorByPlate && plateInfo) {
        fill = plateColor(plateInfo.index)
      }

      return (
        <circle
          key={cell.id}
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
        />
      )
    })
  }, [
    voronoiCells, project, zoom, viewWidth, viewHeight,
    plateByCell, colorByPlate, showVoronoi,
    hoveredCell, selectedCells, onCellHover, onCellClick, strokeWidth,
  ])

  // Plate boundary outlines (simplified: draw lines between cells of different plates)
  const plateBoundaries = useMemo(() => {
    if (!showPlates || plates.length === 0) return null

    const boundaries: { x1: number; y1: number; x2: number; y2: number }[] = []
    voronoiCells.forEach((cell) => {
      const myPlate = plateByCell.get(cell.id)?.id
      cell.neighbors.forEach((nbId) => {
        if (nbId > cell.id) {
          const nbPlate = plateByCell.get(nbId)?.id
          if (myPlate && nbPlate && myPlate !== nbPlate) {
            const nb = voronoiCells[nbId]
            if (nb) {
              const p1 = project(cell.lon, cell.lat)
              const p2 = project(nb.lon, nb.lat)
              boundaries.push({ x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y })
            }
          }
        }
      })
    })

    return boundaries.map((b, i) => (
      <line
        key={i}
        x1={b.x1}
        y1={b.y1}
        x2={b.x2}
        y2={b.y2}
        stroke="#e63946"
        strokeWidth={strokeWidth * 2}
        strokeOpacity={0.7}
        strokeLinecap="round"
      />
    ))
  }, [voronoiCells, plates, plateByCell, showPlates, project, strokeWidth])

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
