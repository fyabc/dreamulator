/**
 * MapSvgOverlay — SVG layer rendered on top of the Three.js terrain canvas.
 *
 * Renders Voronoi cells, plate boundaries, rivers, and labels as SVG
 * elements.  Coordinates are transformed from (lon, lat) to viewport
 * pixels using the current camera transform.
 *
 * When CVT mesh data (vertices + regions) is available, Voronoi cells
 * are rendered as polygons instead of circles at cell centers.
 */

import { useMemo } from 'react'
import type {
  VoronoiCell,
  TectonicPlate,
  MapFeature,
  CVTMesh,
  BoundaryType,
} from '../../viewers/map/types'
import type { ColorMode } from '../../viewers/map/TerrainPlane'
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
  /** CVT mesh data for polygon rendering (optional). */
  cvtMesh?: CVTMesh | null

  // Visibility
  showVoronoi: boolean
  showPlates: boolean
  showFeatures: boolean

  // Interaction
  hoveredCell: number | null
  selectedCells: Set<number>
  onCellHover: (cellId: number | null) => void
  onCellClick: (cellId: number, shiftKey: boolean) => void

  // Color mode (to determine cell coloring strategy)
  colorMode: ColorMode
}

/** Colors for boundary types. */
const BOUNDARY_COLORS: Record<BoundaryType, string> = {
  convergent: '#e63946',
  divergent: '#2dc653',
  transform: '#f4d35e',
}

export default function MapSvgOverlay({
  viewWidth,
  viewHeight,
  project,
  zoom,
  voronoiCells,
  plates,
  features,
  cvtMesh,
  showVoronoi,
  showPlates,
  showFeatures,
  hoveredCell,
  selectedCells,
  onCellHover,
  onCellClick,
  colorMode,
}: MapSvgOverlayProps) {
  // Build plate lookup
  const plateByCell = useMemo(() => {
    const map = new Map<number, { id: string; index: number }>()
    plates.forEach((plate, idx) => {
      plate.cell_ids.forEach((cid) => map.set(cid, { id: plate.id, index: idx }))
    })
    return map
  }, [plates])

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

  // Determine if we should color cells by plate or boundary
  const colorByPlate = colorMode === 'plates' || showPlates
  const colorByBoundary = colorMode === 'boundaries'

  // Compute fill color for a cell based on the current coloring mode
  const getCellFill = (cellId: number): { fill: string; fillOpacity: number } => {
    if (colorByBoundary && regionByCell) {
      // In boundaries mode, fill each cell with a dimmed base; boundaries drawn separately
      return { fill: '#333', fillOpacity: 0.15 }
    }
    if (colorByPlate) {
      const plateInfo = plateByCell.get(cellId)
      if (plateInfo) {
        return { fill: plateColor(plateInfo.index), fillOpacity: 0.3 }
      }
    }
    return { fill: 'transparent', fillOpacity: 0 }
  }

  // Render Voronoi cells — polygons (if CVT mesh available) or circles (fallback)
  const cellElements = useMemo(() => {
    const shouldRender = showVoronoi || colorByPlate || colorByBoundary
    if (!shouldRender) return null

    // Polygon rendering when CVT mesh is available
    if (vertexLookup && regionByCell) {
      return voronoiCells.flatMap((cell) => {
        const region = regionByCell.get(cell.id)
        if (!region || !region.vertex_ids || region.vertex_ids.length < 3) {
          return []
        }

        const isHovered = hoveredCell === cell.id
        const isSelected = selectedCells.has(cell.id)
        const { fill, fillOpacity } = getCellFill(cell.id)

        // Build polygon points from vertices
        const polyPoints: string[] = []
        for (const vid of region.vertex_ids) {
          const v = vertexLookup.get(vid)
          if (!v) continue
          polyPoints.push(`${v.lon},${v.lat}`)
        }
        if (polyPoints.length < 3) return []

        const polygons: React.ReactNode[] = []
        for (const offset of wrapOffsets) {
          // Project all vertices with the current longitude offset
          const projectedPoints = region.vertex_ids
            .map((vid) => {
              const v = vertexLookup.get(vid)
              if (!v) return null
              const p = project(v.lon + offset, v.lat)
              return p
            })
            .filter((p): p is { x: number; y: number } => p !== null)

          if (projectedPoints.length < 3) continue

          // Bounding box check for viewport culling
          const minX = Math.min(...projectedPoints.map((p) => p.x))
          const maxX = Math.max(...projectedPoints.map((p) => p.x))
          const minY = Math.min(...projectedPoints.map((p) => p.y))
          const maxY = Math.max(...projectedPoints.map((p) => p.y))
          if (maxX < -20 || minX > viewWidth + 20 || maxY < -20 || minY > viewHeight + 20) continue

          // Skip polygons that span more than half the map width (wrap artifacts)
          if (maxX - minX > viewWidth * 0.8) continue

          const pointsStr = projectedPoints.map((p) => `${p.x},${p.y}`).join(' ')

          polygons.push(
            <polygon
              key={`${cell.id}_${offset}`}
              points={pointsStr}
              fill={fill}
              fillOpacity={fillOpacity}
              stroke={isSelected ? '#ff0' : isHovered ? '#0ff' : colorByPlate ? fill : '#666'}
              strokeWidth={isSelected || isHovered ? strokeWidth * 2 : strokeWidth}
              strokeOpacity={isSelected ? 1 : isHovered ? 0.8 : showVoronoi ? 0.3 : 0.1}
              style={{ cursor: 'pointer' }}
              onMouseEnter={() => onCellHover(cell.id)}
              onMouseLeave={() => onCellHover(null)}
              onClick={(e) => onCellClick(cell.id, e.shiftKey)}
            />,
          )
        }
        return polygons
      })
    }

    // Fallback: render as circles at cell centers
    return voronoiCells.flatMap((cell) => {
      const { fill, fillOpacity } = getCellFill(cell.id)
      const isHovered = hoveredCell === cell.id
      const isSelected = selectedCells.has(cell.id)

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
            fillOpacity={fillOpacity}
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
    plateByCell, colorByPlate, colorByBoundary, showVoronoi,
    hoveredCell, selectedCells, onCellHover, onCellClick, strokeWidth,
    vertexLookup, regionByCell,
  ])

  // Plate boundary rendering — use CVT mesh boundary data if available,
  // otherwise fall back to cell-neighbor comparison
  const plateBoundaries = useMemo(() => {
    if (!showPlates && !colorByBoundary) return null
    if (plates.length === 0 && !cvtMesh) return null

    // Map width in screen pixels (for culling stretched wrap-around segments)
    const mapScreenWidth = Math.abs(project(180, 0).x - project(-180, 0).x)

    const lines: React.ReactNode[] = []
    let idx = 0

    if (cvtMesh && regionByCell && vertexLookup && colorByBoundary) {
      // Render boundary segments with type-specific colors from CVT mesh
      for (const region of cvtMesh.regions) {
        if (!region.boundaries) continue
        for (const [nbIdStr, bType] of Object.entries(region.boundaries)) {
          const nbId = parseInt(nbIdStr, 10)
          if (nbId <= region.id) continue // avoid duplicate segments

          const nbRegion = regionByCell.get(nbId)
          if (!nbRegion) continue

          // Find shared vertices between the two regions
          const sharedVerts = region.vertex_ids.filter((v) =>
            nbRegion.vertex_ids.includes(v),
          )
          if (sharedVerts.length < 2) continue

          for (const offset of wrapOffsets) {
            // Draw lines between consecutive shared vertices
            for (let i = 0; i < sharedVerts.length - 1; i++) {
              const v1 = vertexLookup.get(sharedVerts[i])
              const v2 = vertexLookup.get(sharedVerts[i + 1])
              if (!v1 || !v2) continue

              const p1 = project(v1.lon + offset, v1.lat)
              const p2 = project(v2.lon + offset, v2.lat)

              if (Math.abs(p1.x - p2.x) > mapScreenWidth * 0.5) continue
              if (p1.x < -50 && p2.x < -50) continue
              if (p1.x > viewWidth + 50 && p2.x > viewWidth + 50) continue
              if (p1.y < -50 && p2.y < -50) continue
              if (p1.y > viewHeight + 50 && p2.y > viewHeight + 50) continue

              lines.push(
                <line
                  key={`cb-${idx++}`}
                  x1={p1.x}
                  y1={p1.y}
                  x2={p2.x}
                  y2={p2.y}
                  stroke={BOUNDARY_COLORS[bType] ?? '#888'}
                  strokeWidth={strokeWidth * 2.5}
                  strokeOpacity={0.8}
                  strokeLinecap="round"
                />,
              )
            }
          }
        }
      }
    } else {
      // Fallback: draw lines between cells of different plates (original logic)
      const rawSegments: { lon1: number; lat1: number; lon2: number; lat2: number }[] = []
      voronoiCells.forEach((cell) => {
        const myPlate = plateByCell.get(cell.id)?.id
        cell.neighbors.forEach((nbId) => {
          if (nbId > cell.id) {
            const nbPlate = plateByCell.get(nbId)?.id
            if (myPlate && nbPlate && myPlate !== nbPlate) {
              const nb = voronoiCells[nbId]
              if (nb) {
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

      for (const seg of rawSegments) {
        for (const offset of wrapOffsets) {
          const p1 = project(seg.lon1 + offset, seg.lat1)
          const p2 = project(seg.lon2 + offset, seg.lat2)
          if (Math.abs(p1.x - p2.x) > mapScreenWidth * 0.5) continue
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
    }

    return lines
  }, [
    voronoiCells, plates, plateByCell, showPlates, colorByBoundary,
    project, strokeWidth, wrapOffsets, cvtMesh, regionByCell, vertexLookup,
  ])

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
