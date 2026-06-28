/**
 * MapViewer — main map container combining Three.js terrain + SVG overlay.
 *
 * Manages camera zoom/pan, projects between geographic and screen coordinates,
 * and dispatches interaction events to child components.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import WebGPURenderer from 'three/examples/jsm/renderers/webgpu/WebGPURenderer.js'
import useTerrainTexture, { type ColorMode } from '../../viewers/map/TerrainPlane'
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
  hillshadeStrength: number
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
  hillshadeStrength,
  readOnly: _readOnly = false,
  onCursorMove,
  onCellHover,
  onCellClick,
  hoveredCell,
  selectedCells,
}: MapViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rendererRef = useRef<InstanceType<typeof WebGPURenderer> | null>(null)
  const sceneRef = useRef<THREE.Scene | null>(null)
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null)
  const meshRef = useRef<THREE.Mesh | null>(null)
  const [containerSize, setContainerSize] = useState({ width: 800, height: 400 })
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 })
  const [webgpuReady, setWebgpuReady] = useState(false)

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

  // Pre-render terrain to a CanvasTexture (CPU-side, no custom shader)
  const terrainTexture = useTerrainTexture({
    elevation,
    width: mapW,
    height: mapH,
    seaLevel,
    colorMode,
    hillshadeStrength,
  })

  // Initialize WebGPURenderer + scene
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    let disposed = false
    const renderer = new WebGPURenderer({ canvas, antialias: true })
    rendererRef.current = renderer

    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#0a0a1a')
    sceneRef.current = scene

    const camera = new THREE.PerspectiveCamera(50, 2, 0.01, 100)
    camera.position.set(0, 5, 0)
    camera.lookAt(0, 0, 0)
    cameraRef.current = camera

    ;(async () => {
      try {
        await renderer.init()
        if (!disposed) setWebgpuReady(true)
      } catch (e) {
        console.warn('WebGPU init failed:', e)
      }
    })()

    return () => {
      disposed = true
      try { renderer.dispose() } catch { /* backend not ready */ }
      scene.clear()
      rendererRef.current = null
      sceneRef.current = null
      cameraRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Update mesh when texture or dimensions change
  useEffect(() => {
    if (!webgpuReady || !sceneRef.current || !cameraRef.current || !rendererRef.current) return
    const scene = sceneRef.current
    const camera = cameraRef.current
    const renderer = rendererRef.current

    // Remove old mesh
    if (meshRef.current) {
      scene.remove(meshRef.current)
      meshRef.current.geometry.dispose()
      if (meshRef.current.material instanceof THREE.Material) {
        meshRef.current.material.dispose()
      }
    }

    if (!terrainTexture) return

    const aspect = mapW / mapH
    const fitH = containerSize.height * 0.9
    const fitW = containerSize.width * 0.9
    const h = fitH
    const w = h * aspect
    const pw = w > fitW ? fitW : w
    const ph = pw / PLANE_ASPECT

    // Convert pixel dimensions to world units (camera at y=5, fov=50)
    const visibleH = 2 * 5 * Math.tan(THREE.MathUtils.degToRad(25))
    const visibleW = visibleH * (containerSize.width / containerSize.height)
    const worldW = (pw / containerSize.width) * visibleW
    const worldH = (ph / containerSize.height) * visibleH

    const geo = new THREE.PlaneGeometry(worldW, worldH)
    const mat = new THREE.MeshBasicMaterial({ map: terrainTexture, side: THREE.DoubleSide })
    const mesh = new THREE.Mesh(geo, mat)
    mesh.rotation.x = -Math.PI / 2
    scene.add(mesh)
    meshRef.current = mesh

    // Update camera aspect
    camera.aspect = containerSize.width / containerSize.height
    camera.updateProjectionMatrix()

    renderer.setSize(containerSize.width, containerSize.height)
    renderer.render(scene, camera)
  }, [webgpuReady, terrainTexture, mapW, mapH, containerSize])

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

  // Re-render on zoom/pan changes
  useEffect(() => {
    if (!webgpuReady || !rendererRef.current || !sceneRef.current || !cameraRef.current || !meshRef.current) return
    const camera = cameraRef.current
    const mesh = meshRef.current

    // Apply zoom by adjusting camera distance
    camera.position.y = 5 / zoom
    camera.lookAt(0, 0, 0)

    // Apply pan by moving mesh (convert pixel pan to world units)
    const visibleH = 2 * (5 / zoom) * Math.tan(THREE.MathUtils.degToRad(25))
    const visibleW = visibleH * (containerSize.width / containerSize.height)
    mesh.position.x = -(pan.x / containerSize.width) * visibleW
    mesh.position.z = -(pan.y / containerSize.height) * visibleH

    rendererRef.current.render(sceneRef.current, camera)
  }, [webgpuReady, zoom, pan, containerSize])

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
      {/* WebGPU terrain canvas */}
      <canvas
        ref={canvasRef}
        className="absolute inset-0"
        style={{ background: '#0a0a1a' }}
      />

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
