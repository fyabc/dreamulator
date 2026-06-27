/**
 * MapViewer — main map container combining Three.js terrain + SVG overlay.
 *
 * Manages camera zoom/pan, projects between geographic and screen coordinates,
 * and dispatches interaction events to child components.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import TerrainPlane, { type ColorMode } from '../../viewers/map/TerrainPlane'
import MapSvgOverlay from './MapSvgOverlay'
import { normalisedToMeters } from '../../viewers/map/utils/projection'
import type {
  MapMetadata,
  VoronoiCell,
  TectonicPlate,
  MapFeature,
} from '../../viewers/map/types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface MapViewerProps {
  metadata: MapMetadata | null
  elevation: Float32Array | null
  voronoiCells: VoronoiCell[]
  plates: TectonicPlate[]
  features: MapFeature[]
  colorMode: ColorMode
  showVoronoi: boolean
  showPlates: boolean
  showFeatures: boolean
  readOnly?: boolean
  onCursorMove?: (info: CursorInfo | null) => void
  onCellHover?: (cellId: number | null) => void
  onCellClick?: (cellId: number, shiftKey: boolean) => void
  hoveredCell: number | null
  selectedCells: Set<number>
}

export interface CursorInfo {
  lon: number
  lat: number
  elevation: number // normalised
  elevationM: number // metres
  pixelX: number
  pixelY: number
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MIN_ZOOM = 0.5
const MAX_ZOOM = 20
const PLANE_ASPECT = 2 // equirectangular 2:1

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MapViewer({
  metadata,
  elevation,
  voronoiCells,
  plates,
  features,
  colorMode,
  showVoronoi,
  showPlates,
  showFeatures,
  readOnly: _readOnly = false,
  onCursorMove,
  onCellHover,
  onCellClick,
  hoveredCell,
  selectedCells,
}: MapViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerSize, setContainerSize] = useState({ width: 800, height: 400 })
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 })

  // Observe container size
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect
      if (width > 0 && height > 0) {
        setContainerSize({ width, height })
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // Map dimensions
  const mapW = metadata?.width ?? 2048
  const mapH = metadata?.height ?? 1024
  const seaLevel = metadata?.sea_level ?? 0.4
  const elevMin = metadata?.elevation_min_m ?? -11000
  const elevMax = metadata?.elevation_max_m ?? 9000

  // Plane dimensions (maintain aspect ratio within container)
  const planeWidth = useMemo(() => {
    const aspect = mapW / mapH
    const fitH = containerSize.height * 0.9
    const fitW = containerSize.width * 0.9
    const h = fitH
    const w = h * aspect
    if (w > fitW) return fitW
    return w
  }, [mapW, mapH, containerSize])
  const planeHeight = planeWidth / PLANE_ASPECT

  // Projection: (lon, lat) → screen (px, py)
  const project = useCallback(
    (lon: number, lat: number) => {
      // Map to normalised [0, 1]
      const nx = (lon + 180) / 360
      const ny = (90 - lat) / 180
      // Map to screen pixels (centred, with zoom and pan)
      const x = (nx - 0.5) * planeWidth * zoom + containerSize.width / 2 + pan.x
      const y = (ny - 0.5) * planeHeight * zoom + containerSize.height / 2 + pan.y
      return { x, y }
    },
    [planeWidth, planeHeight, zoom, pan, containerSize],
  )

  // Inverse projection: screen (px, py) → (lon, lat)
  const unproject = useCallback(
    (px: number, py: number) => {
      const nx = (px - containerSize.width / 2 - pan.x) / (planeWidth * zoom) + 0.5
      const ny = (py - containerSize.height / 2 - pan.y) / (planeHeight * zoom) + 0.5
      const lon = nx * 360 - 180
      const lat = 90 - ny * 180
      return { lon, lat, nx, ny }
    },
    [planeWidth, planeHeight, zoom, pan, containerSize],
  )

  // Mouse move handler
  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect || !elevation) return
      const px = e.clientX - rect.left
      const py = e.clientY - rect.top

      if (isDragging) {
        setPan({
          x: dragStart.current.panX + (px - dragStart.current.x),
          y: dragStart.current.panY + (py - dragStart.current.y),
        })
        return
      }

      const { lon, lat, nx, ny } = unproject(px, py)
      if (nx < 0 || nx > 1 || ny < 0 || ny > 1) {
        onCursorMove?.(null)
        return
      }

      const pixelX = Math.floor(nx * mapW)
      const pixelY = Math.floor(ny * mapH)
      const elev = elevation[pixelY * mapW + pixelX] ?? 0
      onCursorMove?.({
        lon: Math.round(lon * 100) / 100,
        lat: Math.round(lat * 100) / 100,
        elevation: elev,
        elevationM: Math.round(normalisedToMeters(elev, elevMin, elevMax)),
        pixelX,
        pixelY,
      })
    },
    [elevation, mapW, mapH, unproject, isDragging, elevMin, elevMax, onCursorMove],
  )

  // Zoom handler
  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault()
      const factor = e.deltaY > 0 ? 0.9 : 1.1
      setZoom((z) => Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z * factor)))
    },
    [],
  )

  // Drag handlers
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button === 0 || e.button === 1) {
        setIsDragging(true)
        dragStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y }
      }
    },
    [pan],
  )

  const handleMouseUp = useCallback(() => setIsDragging(false), [])

  // Three.js camera setup for 2D view
  const cameraProps = useMemo(
    () => ({
      position: [0, 5, 0] as [number, number, number],
      fov: 50,
      near: 0.01,
      far: 100,
    }),
    [],
  )

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full overflow-hidden bg-[#0a0a1a] rounded-lg select-none"
      style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
      onMouseMove={handleMouseMove}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      onMouseLeave={() => {
        handleMouseUp()
        onCursorMove?.(null)
      }}
    >
      {/* Three.js terrain canvas */}
      <Canvas
        className="absolute inset-0"
        camera={cameraProps}
        gl={{ antialias: true, alpha: false }}
        style={{ background: '#0a0a1a' }}
      >
        <ambientLight intensity={1} />
        <TerrainPlane
          elevation={elevation}
          width={mapW}
          height={mapH}
          seaLevel={seaLevel}
          colorMode={colorMode}
          planeWidth={planeWidth}
          planeHeight={planeHeight}
        />
      </Canvas>

      {/* SVG overlay */}
      <MapSvgOverlay
        viewWidth={containerSize.width}
        viewHeight={containerSize.height}
        project={project}
        zoom={zoom}
        voronoiCells={voronoiCells}
        plates={plates}
        features={features}
        showVoronoi={showVoronoi}
        showPlates={showPlates}
        showFeatures={showFeatures}
        hoveredCell={hoveredCell}
        selectedCells={selectedCells}
        onCellHover={onCellHover ?? (() => {})}
        onCellClick={onCellClick ?? (() => {})}
        colorByPlate={showPlates}
      />

      {/* Zoom indicator */}
      <div className="absolute bottom-2 right-2 text-xs text-gray-500 bg-black/50 px-2 py-1 rounded font-mono z-20">
        {zoom.toFixed(1)}x
      </div>
    </div>
  )
}
