/**
 * MapViewer — main map container combining Three.js terrain + SVG overlay.
 *
 * Manages camera zoom/pan, projects between geographic and screen coordinates,
 * and dispatches interaction events to child components.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { WebGLRenderer } from 'three'
import WebGPURenderer from 'three/examples/jsm/renderers/webgpu/WebGPURenderer.js'
import useTerrainTexture, { type ColorMode } from '../../viewers/map/TerrainPlane'
import MapSvgOverlay from './MapSvgOverlay'
import {
  normalisedToMeters,
  projectForward,
  projectInverse,
  type ProjectionType,
} from '../../viewers/map/utils/projection'
import type {
  MapMetadata,
  VoronoiCell,
  TectonicPlate,
  MapFeature,
  CVTMesh,
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
  /** CVT mesh data for polygon rendering (optional). */
  cvtMesh?: CVTMesh | null
  colorMode: ColorMode
  /** Map projection to use for coordinate conversion. */
  projection?: ProjectionType
  showVoronoi: boolean
  showPlates: boolean
  showFeatures: boolean
  onZoomChange?: (zoom: number) => void
  onViewStateChange?: (state: { pan: { x: number; y: number }; zoom: number; containerWidth: number; containerHeight: number; planeWidth: number; planeHeight: number }) => void
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
  cvtMesh,
  colorMode,
  projection = 'equirectangular',
  showVoronoi,
  showPlates,
  showFeatures,
  onZoomChange,
  onViewStateChange,
  onCursorMove,
  onCellHover,
  onCellClick,
  hoveredCell,
  selectedCells,
}: MapViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- union of WebGPURenderer | WebGLRenderer
  const rendererRef = useRef<any>(null)
  const sceneRef = useRef<THREE.Scene | null>(null)
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null)
  const meshRef = useRef<THREE.Mesh | null>(null)
  const ghostLeftRef = useRef<THREE.Mesh | null>(null)
  const ghostRightRef = useRef<THREE.Mesh | null>(null)
  const [containerSize, setContainerSize] = useState({ width: 800, height: 400 })
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [isDragging, setIsDragging] = useState(false)
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 })
  const panWrapOffset = useRef(0) // cumulative offset from horizontal wrapping
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

  // Clamp zoom and pan when container size changes
  useEffect(() => {
    const aspect = mapW / mapH
    const wByH = containerSize.height * aspect
    const pw = wByH < containerSize.width ? containerSize.width : wByH
    const ph = pw / PLANE_ASPECT
    const minZoom = Math.max(containerSize.width / pw, containerSize.height / ph)
    const clampedZoom = Math.max(minZoom, Math.min(MAX_ZOOM, zoom))

    setZoom(clampedZoom)
    setPan((p) => {
      const mapHScreen = ph * clampedZoom
      const maxPanY = mapHScreen > containerSize.height
        ? (mapHScreen - containerSize.height) / 2
        : 0
      return { x: p.x, y: Math.max(-maxPanY, Math.min(maxPanY, p.y)) }
    })
  }, [containerSize, mapW, mapH]) // eslint-disable-line react-hooks/exhaustive-deps

  // Pre-render terrain to a CanvasTexture (CPU-side, no custom shader)
  const terrainTexture = useTerrainTexture({
    elevation,
    width: mapW,
    height: mapH,
    seaLevel,
    colorMode,
    hillshadeStrength: 0.7,
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
        console.warn('WebGPU init failed, falling back to WebGL:', e)
        try { renderer.dispose() } catch { /* ignore */ }
        if (disposed) return
        const fallback = new WebGLRenderer({ canvas, antialias: true })
        rendererRef.current = fallback
        if (!disposed) setWebgpuReady(true)
      }
    })()

    return () => {
      disposed = true
      try { rendererRef.current?.dispose() } catch { /* ignore */ }
      scene.clear()
      rendererRef.current = null
      sceneRef.current = null
      cameraRef.current = null
      meshRef.current = null
      ghostLeftRef.current = null
      ghostRightRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Update mesh when texture or dimensions change
  useEffect(() => {
    if (!webgpuReady || !sceneRef.current || !cameraRef.current || !rendererRef.current) return
    const scene = sceneRef.current
    const camera = cameraRef.current
    const renderer = rendererRef.current

    // Remove old mesh + ghosts
    for (const m of [meshRef.current, ghostLeftRef.current, ghostRightRef.current]) {
      if (m) {
        scene.remove(m)
        m.geometry.dispose()
        if (m.material instanceof THREE.Material) m.material.dispose()
      }
    }
    ghostLeftRef.current = null
    ghostRightRef.current = null

    if (!terrainTexture) return

    const aspect = mapW / mapH
    const wByH = containerSize.height * aspect
    const pw = wByH < containerSize.width ? containerSize.width : wByH
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

    // Ghost meshes for seamless horizontal wrapping (cylindrical projection)
    const ghostMat = new THREE.MeshBasicMaterial({ map: terrainTexture, side: THREE.DoubleSide })
    const ghostLeft = new THREE.Mesh(geo, ghostMat)
    ghostLeft.rotation.x = -Math.PI / 2
    scene.add(ghostLeft)
    ghostLeftRef.current = ghostLeft

    const ghostRightMat = new THREE.MeshBasicMaterial({ map: terrainTexture, side: THREE.DoubleSide })
    const ghostRight = new THREE.Mesh(geo, ghostRightMat)
    ghostRight.rotation.x = -Math.PI / 2
    scene.add(ghostRight)
    ghostRightRef.current = ghostRight

    // Update camera aspect
    camera.aspect = containerSize.width / containerSize.height
    camera.updateProjectionMatrix()

    renderer.setSize(containerSize.width, containerSize.height)
    renderer.render(scene, camera)
  }, [webgpuReady, terrainTexture, mapW, mapH, containerSize])

  // Plane dimensions (cover container — map always fills viewport, excess is clipped)
  const planeWidth = useMemo(() => {
    const aspect = mapW / mapH
    const wByH = containerSize.height * aspect
    return wByH < containerSize.width ? containerSize.width : wByH
  }, [mapW, mapH, containerSize])
  const planeHeight = planeWidth / PLANE_ASPECT

  // Projection: (lon, lat) → screen (px, py)
  // Uses unwrapped pan.x so SVG elements stay at continuous screen positions
  const project = useCallback(
    (lon: number, lat: number) => {
      const { nx, ny } = projectForward(projection, lon, lat)
      const unwrappedPanX = pan.x + panWrapOffset.current
      const x = (nx - 0.5) * planeWidth * zoom + containerSize.width / 2 + unwrappedPanX
      const y = (ny - 0.5) * planeHeight * zoom + containerSize.height / 2 + pan.y
      return { x, y }
    },
    [projection, planeWidth, planeHeight, zoom, pan, containerSize],
  )

  // Inverse projection: screen (px, py) → (lon, lat)
  const unproject = useCallback(
    (px: number, py: number) => {
      const unwrappedPanX = pan.x + panWrapOffset.current
      const nx = (px - containerSize.width / 2 - unwrappedPanX) / (planeWidth * zoom) + 0.5
      const ny = (py - containerSize.height / 2 - pan.y) / (planeHeight * zoom) + 0.5
      const { lon, lat } = projectInverse(projection, nx, ny)
      return { lon, lat, nx, ny }
    },
    [projection, planeWidth, planeHeight, zoom, pan, containerSize],
  )

  // Clamp pan to keep map within vertical bounds (cylindrical projection: horizontal wraps)
  const clampPan = useCallback(
    (px: number, py: number) => {
      const mapH = planeHeight * zoom
      const maxPanY = mapH > containerSize.height
        ? (mapH - containerSize.height) / 2
        : 0
      return { x: px, y: Math.max(-maxPanY, Math.min(maxPanY, py)) }
    },
    [planeHeight, zoom, containerSize.height],
  )

  // Mouse move handler
  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect || !elevation) return
      const px = e.clientX - rect.left
      const py = e.clientY - rect.top

      if (isDragging) {
        const rawX = dragStart.current.panX + (px - dragStart.current.x)
        const rawY = dragStart.current.panY + (py - dragStart.current.y)

        // Wrap horizontal pan to stay within ±1 map width (seamless cylindrical projection)
        const mapWidthPx = planeWidth * zoom
        const halfW = mapWidthPx / 2
        let wrappedX = rawX
        if (mapWidthPx > 0) {
          wrappedX = ((rawX + halfW) % mapWidthPx + mapWidthPx) % mapWidthPx - halfW
        }
        // Track cumulative offset so SVG projection stays continuous
        panWrapOffset.current += rawX - wrappedX

        const clamped = clampPan(wrappedX, rawY)
        setPan(clamped)
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
    [elevation, mapW, mapH, unproject, isDragging, clampPan, elevMin, elevMax, onCursorMove],
  )

  // Zoom handler
  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault()
      const factor = e.deltaY > 0 ? 0.9 : 1.1
      const minZoom = Math.max(
        containerSize.width / planeWidth,
        containerSize.height / planeHeight,
      )
      setZoom((z) => Math.max(minZoom, Math.min(MAX_ZOOM, z * factor)))
    },
    [containerSize, planeWidth, planeHeight],
  )

  // Drag handlers
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button === 0 || e.button === 1) {
        const rect = containerRef.current?.getBoundingClientRect()
        if (!rect) return
        setIsDragging(true)
        dragStart.current = {
          x: e.clientX - rect.left,
          y: e.clientY - rect.top,
          panX: pan.x,
          panY: pan.y,
        }
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

    // Compute effective zoom (clamp to min that fills viewport)
    const minZoom = Math.max(
      containerSize.width / planeWidth,
      containerSize.height / planeHeight,
    )
    const effectiveZoom = Math.max(minZoom, zoom)

    // Clamp pan.y to keep map within vertical bounds
    const mapHScreen = planeHeight * effectiveZoom
    const maxPanY = mapHScreen > containerSize.height
      ? (mapHScreen - containerSize.height) / 2
      : 0
    const clampedPanY = Math.max(-maxPanY, Math.min(maxPanY, pan.y))

    // Apply zoom by adjusting camera distance
    camera.position.y = 5 / effectiveZoom
    camera.lookAt(0, 0, 0)

    // Apply pan by moving mesh (convert pixel pan to world units)
    // Camera at (0, h, 0) looking down with up=(0,1,0):
    //   lookAt resolves degenerate case → camera right = +X, camera up = -Z
    //   Projection: screenX ∝ +meshX, screenY ∝ +meshZ (screen Y points down)
    const visibleH = 2 * (5 / effectiveZoom) * Math.tan(THREE.MathUtils.degToRad(25))
    const visibleW = visibleH * (containerSize.width / containerSize.height)
    const meshX = (pan.x / containerSize.width) * visibleW
    const meshZ = (clampedPanY / containerSize.height) * visibleH
    mesh.position.x = meshX
    mesh.position.z = meshZ

    // Position ghost meshes for seamless horizontal wrapping
    const worldW = (mesh.geometry as THREE.PlaneGeometry).parameters.width
    if (ghostLeftRef.current) {
      ghostLeftRef.current.position.set(meshX - worldW, 0, meshZ)
    }
    if (ghostRightRef.current) {
      ghostRightRef.current.position.set(meshX + worldW, 0, meshZ)
    }

    rendererRef.current.render(sceneRef.current, camera)
    onZoomChange?.(effectiveZoom)
    onViewStateChange?.({
      pan, zoom: effectiveZoom,
      containerWidth: containerSize.width, containerHeight: containerSize.height,
      planeWidth, planeHeight,
    })
  }, [webgpuReady, zoom, pan, containerSize, planeWidth, planeHeight, onZoomChange, onViewStateChange])

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
      {/* Terrain canvas (WebGPU with WebGL fallback) */}
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
        cvtMesh={cvtMesh}
        showVoronoi={showVoronoi}
        showPlates={showPlates}
        showFeatures={showFeatures}
        hoveredCell={hoveredCell}
        selectedCells={selectedCells}
        onCellHover={onCellHover ?? (() => {})}
        onCellClick={onCellClick ?? (() => {})}
        colorMode={colorMode}
      />

    </div>
  )
}
