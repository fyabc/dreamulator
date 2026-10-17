/**
 * MapViewer — main map container combining Three.js terrain + SVG overlay.
 *
 * Coordinate system (mapCoords.ts):
 *   View state = { mapCenter: {lon, lat}, zoom }
 *   Forward:  geographic → screen via lonLatToScreen()
 *   Reverse:  screen → geographic via screenToLonLat()
 *   Drag:     pixel delta → mapCenter delta via applyDrag()
 *   Zoom:     factor → new mapCenter + zoom via applyZoom()
 *
 * mapCenter.lon wraps modulo 360° so it never overflows.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { WebGLRenderer } from 'three'
import useCellIdMap from '../../viewers/map/useCellIdMap'
import useGPUTerrain from '../../viewers/map/useGPUTerrain'
import useRafCoalesced from '../../viewers/map/useRafCoalesced'
import MapSvgOverlay from './MapSvgOverlay'
import { normalisedToMeters } from '../../viewers/map/utils/mapCoords'
import {
  lonLatToScreen,
  screenToLonLat,
  applyDrag,
  type MapViewState,
  type LonLat,
  type Viewport,
} from '../../viewers/map/utils/mapCoords'
import type {
  ColorMode,
  MapMetadata,
  VoronoiCell,
  CVTMesh,
} from '../../viewers/map/types'
import { buildCellKDTree, type KDTree3D } from './utils/kdtree'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface MapViewerProps {
  metadata: MapMetadata | null
  elevation: Float32Array | null
  voronoiCells: VoronoiCell[]
  cvtMesh?: CVTMesh | null
  layers?: Record<ColorMode, number>
  onZoomChange?: (zoom: number) => void
  onViewStateChange?: (state: {
    mapCenter: LonLat
    zoom: number
    containerWidth: number
    containerHeight: number
  }) => void
  onCursorMove?: (info: CursorInfo | null) => void
  onCellHover?: (cellId: number | null) => void
  onCellClick?: (cellId: number, ctrlKey: boolean) => void
  hoveredCell: number | null
  selectedCells: Set<number>
  /** Subsolar longitude in degrees (day/night overlay). */
  sunLongitudeDeg?: number
  /** Solar declination in degrees (day/night overlay). */
  solarDeclinationDeg?: number
  /** Enable the day/night overlay. */
  dayNight?: boolean
  /** Monthly temperature/precipitation/pressure textures (Phase 4 / debt 24),
   *  baked by the caller.  Pressure is monthly-only (no annual counterpart). */
  monthlyTemperature?: THREE.DataTexture | null
  monthlyPrecipitation?: THREE.DataTexture | null
  monthlyPressure?: THREE.DataTexture | null
  monthlyPressureError?: THREE.DataTexture | null
  monthlySlp?: THREE.DataTexture | null
  /** UCC classification thematic texture (UCC-01 step 4a), baked by the caller
   *  from `bakeUccLayer`; null when the yearly file lacks the fields. */
  uccTexture?: THREE.DataTexture | null
  /** Monthly wind arrows (tech debt 24): N×12 components in mesh-cell order. */
  monthlyWindEast?: Float32Array | null
  monthlyWindNorth?: Float32Array | null
  month?: number
  /** Render the SVG graticule. Off in clean/recording mode. */
  showGraticule?: boolean
}

export interface CursorInfo {
  lon: number
  lat: number
  elevation: number
  elevationM: number
  pixelX: number
  pixelY: number
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_ZOOM = 20
// camera visible height at zoom=1
const BASE_VIS_H = 2 * 5 * Math.tan(THREE.MathUtils.degToRad(25))

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MapViewer({
  metadata,
  elevation,
  voronoiCells,
  cvtMesh,
  layers,
  onZoomChange,
  onViewStateChange,
  onCursorMove,
  onCellHover,
  onCellClick,
  hoveredCell,
  selectedCells,
  sunLongitudeDeg = 0,
  solarDeclinationDeg = 0,
  dayNight = false,
  monthlyTemperature = null,
  monthlyPrecipitation = null,
  monthlyPressure = null,
  monthlyPressureError = null,
  monthlySlp = null,
  uccTexture = null,
  monthlyWindEast = null,
  monthlyWindNorth = null,
  month = 0,
  showGraticule = true,
}: MapViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rendererRef = useRef<WebGLRenderer | null>(null)
  const sceneRef = useRef<THREE.Scene | null>(null)
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null)
  const meshRef = useRef<THREE.Mesh | null>(null)
  const ghostLeftRef = useRef<THREE.Mesh | null>(null)
  const ghostRightRef = useRef<THREE.Mesh | null>(null)
  const [containerSize, setContainerSize] = useState({ width: 800, height: 400 })
  const [webgpuReady, setWebgpuReady] = useState(false)

  // --- View state ---
  const [mapCenter, setMapCenter] = useState<LonLat>({ lon: 0, lat: 0 })
  const [zoom, setZoomState] = useState(1)

  // --- Refs for render loop (updated synchronously with state) ---
  const mapCenterRef = useRef<LonLat>({ lon: 0, lat: 0 })
  const zoomRef = useRef(1)
  const containerRef2 = useRef({ width: 800, height: 400 })

  // Sync helpers: update BOTH state and ref immediately
  const syncMapCenter = useCallback((mc: LonLat) => {
    mapCenterRef.current = mc
    setMapCenter(mc)
  }, [])
  const syncZoom = useCallback((z: number) => {
    zoomRef.current = z
    setZoomState(z)
  }, [])

  // Map dimensions
  const mapW = metadata?.width ?? 2048
  const mapH = metadata?.height ?? 1024
  const seaLevel = metadata?.sea_level_m ?? 0.0
  const elevMin = metadata?.elevation_min_m ?? -11000
  const elevMax = metadata?.elevation_max_m ?? 9000

  // KD-tree
  const kdTree = useMemo<KDTree3D | null>(() => {
    if (!voronoiCells || voronoiCells.length === 0) return null
    return buildCellKDTree(voronoiCells)
  }, [voronoiCells])

  // Cell-ID map
  const cellIdMap = useCellIdMap({ cvtMesh, width: mapW, height: mapH })

  // Loading indicator (useEffect avoids rAF in render body, enables cleanup)
  const [isRendering, setIsRendering] = useState(false)
  useEffect(() => {
    setIsRendering(true)
    const rafId = requestAnimationFrame(() => setIsRendering(false))
    return () => cancelAnimationFrame(rafId)
  }, [layers, cellIdMap])

  // Drag state
  const [isDragging, setIsDragging] = useState(false)
  const dragStart = useRef({ x: 0, y: 0, mapCenter: { lon: 0, lat: 0 } })

  // rAF throttle
  const rafRef = useRef<number>(0)
  const lastMousePos = useRef<{ px: number; py: number } | null>(null)

  // --- Sync container ref (mapCenter/zoom are synced directly via sync helpers) ---
  useEffect(() => {
    containerRef2.current = containerSize
  }, [containerSize])

  // --- Container resize observer ---
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const observer = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect
      if (width > 0 && height > 0) setContainerSize({ width, height })
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // --- Day/night sun params (radians for the shaders / CPU pass) ---
  const sunLonRad = (sunLongitudeDeg * Math.PI) / 180
  const sunDecRad = (solarDeclinationDeg * Math.PI) / 180
  const dayNightNum = dayNight ? 1 : 0

  // --- GPU materials ---
  // Cell hover/selection highlights are drawn by the SVG overlay (not baked
  // into the texture), so hovering never triggers a texture re-bake.

  // Opacity sliders fire many events per frame; coalesce so the composite
  // pass (and any data-driven re-bake) runs at most once per animation frame.
  const renderLayers = useRafCoalesced(layers)

  const { material: gpuMaterial, renderComposite: gpuRenderComposite } = useGPUTerrain({
    elevation, width: mapW, height: mapH, seaLevel,
    elevMinM: elevMin, elevMaxM: elevMax,
    layers: renderLayers, cvtMesh, cellIdMap,
    monthlyTemperature, monthlyPrecipitation, monthlyPressure, monthlyPressureError,
    monthlySlp,
    uccTexture,
    flipHorizontal: false,  // PlaneGeometry, not SphereGeometry
    sunLonRad, sunDecRad, dayNight: dayNightNum,
  })

  // Ref so the (stable) rAF render loop always sees the current callback.
  const gpuCompositeRef = useRef(gpuRenderComposite)
  gpuCompositeRef.current = gpuRenderComposite

  const useGPU = gpuMaterial !== null

  // --- WebGL init ---
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const renderer = new WebGLRenderer({ canvas, antialias: true })
    // sRGB textures + sRGB output: decode on sample, encode on write — a correct
    // round-trip for the pre-baked sRGB colour data (no double-encoding).
    renderer.outputColorSpace = THREE.SRGBColorSpace
    rendererRef.current = renderer
    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#0a0a1a')
    sceneRef.current = scene
    const camera = new THREE.PerspectiveCamera(50, 2, 0.01, 100)
    camera.position.set(0, 5, 0)
    camera.lookAt(0, 0, 0)
    cameraRef.current = camera
    setWebgpuReady(true)
    return () => {
      try { rendererRef.current?.dispose() } catch { /* ignore */ }
      scene.clear()
      rendererRef.current = null
      sceneRef.current = null
      cameraRef.current = null
      meshRef.current = null
      ghostLeftRef.current = null
      ghostRightRef.current = null
    }
  }, [])

  // --- Mesh creation ---
  useEffect(() => {
    if (!webgpuReady || !sceneRef.current || !cameraRef.current || !rendererRef.current) return
    const scene = sceneRef.current
    const camera = cameraRef.current
    const renderer = rendererRef.current

    for (const m of [meshRef.current, ghostLeftRef.current, ghostRightRef.current]) {
      if (m) { scene.remove(m); m.geometry.dispose(); if (m.material instanceof THREE.Material) m.material.dispose() }
    }
    ghostLeftRef.current = null; ghostRightRef.current = null
    let mat: THREE.Material | null
    if (useGPU) {
      mat = gpuMaterial!
    } else {
      mat = null
    }
    if (!mat) return

    const visW = BASE_VIS_H * (containerSize.width / containerSize.height)
    const geo = new THREE.PlaneGeometry(visW, BASE_VIS_H)
    const mesh = new THREE.Mesh(geo, mat)
    mesh.rotation.x = -Math.PI / 2
    scene.add(mesh)
    meshRef.current = mesh

    // Ghost meshes: the cylindrical projection wraps horizontally, so the
    // seam is hidden by repeating the plane one width to each side.
    for (const dir of [-1, 1]) {
      const g = new THREE.Mesh(geo, gpuMaterial!)
      g.rotation.x = -Math.PI / 2
      scene.add(g)
      if (dir === -1) ghostLeftRef.current = g
      else ghostRightRef.current = g
    }

    camera.aspect = containerSize.width / containerSize.height
    camera.updateProjectionMatrix()
    renderer.setSize(containerSize.width, containerSize.height)
    gpuCompositeRef.current?.(renderer)
    renderer.render(scene, camera)

    return () => {
      // Cleanup meshes on unmount / re-creation
      for (const ref of [meshRef, ghostLeftRef, ghostRightRef]) {
        const m = ref.current
        if (m) {
          scene.remove(m)
          m.geometry?.dispose()
          if (m.material instanceof THREE.Material) m.material.dispose()
        }
      }
    }
  }, [webgpuReady, useGPU, gpuMaterial, mapW, mapH, containerSize])

  // --- Viewport (used by mapCoords functions) ---
  // Memoised so `project` (and the SVG graticule that depends on it) only
  // recompute on pan/zoom/resize, not on every hover re-render.
  const vp: Viewport = useMemo(
    () => ({ width: containerSize.width, height: containerSize.height }),
    [containerSize],
  )

  // --- Forward projection (for SVG overlay) ---
  const project = useCallback(
    (lon: number, lat: number) => {
      // Use ref for zoom to stay in sync with render loop (no 1-frame lag)
      return lonLatToScreen({ lon, lat }, { mapCenter: mapCenterRef.current, zoom: zoomRef.current }, vp)
    },
    // Refs used inside for accuracy (no 1-frame lag), but mapCenter/zoom
    // in deps to trigger SVG re-render on pan.
    [vp, mapCenter, zoom, containerSize],
  )

  // --- Reverse projection (screen → geographic) ---
  const unproject = useCallback(
    (px: number, py: number) => {
      return screenToLonLat(px, py, { mapCenter: mapCenterRef.current, zoom: zoomRef.current }, vp)
    },
    [vp, mapCenter, zoom, containerSize],
  )

  // --- Continuous render loop ---
  useEffect(() => {
    let rafId: number
    const loop = () => {
      const renderer = rendererRef.current
      const scene = sceneRef.current
      const camera = cameraRef.current
      const mesh = meshRef.current
      if (renderer && scene && camera && mesh) {
        const cs = containerRef2.current
        const mc = mapCenterRef.current
        const z = Math.max(1, Math.min(MAX_ZOOM, zoomRef.current))
        const visW = BASE_VIS_H * (cs.width / cs.height)

        camera.position.y = 5 / z
        camera.lookAt(0, 0, 0)

        // Mesh displacement: mapCentre lon/lat → world X/Z.
        // Rotation -π/2 around X: world = (lx+meshX, 0, ly+meshZ).
        // meshX = -(nx - 0.5) * visW, meshZ = -(ny - 0.5) * BASE_VIS_H
        mesh.position.x = -(mc.lon / 360) * visW
        mesh.position.z = (mc.lat / 180) * BASE_VIS_H

        const worldW = (mesh.geometry as THREE.PlaneGeometry).parameters.width
        if (ghostLeftRef.current)
          ghostLeftRef.current.position.set(mesh.position.x - worldW, 0, mesh.position.z)
        if (ghostRightRef.current)
          ghostRightRef.current.position.set(mesh.position.x + worldW, 0, mesh.position.z)

        // Compose layer textures into the shared target (cheap fullscreen quad).
        gpuCompositeRef.current?.(renderer)
        renderer.render(scene, camera)
      }
      rafId = requestAnimationFrame(loop)
    }
    rafId = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(rafId)
  }, [])

  // --- Mouse handlers ---

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button !== 0 && e.button !== 1) return
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      setIsDragging(true)
      dragStart.current = {
        x: e.clientX - rect.left,
        y: e.clientY - rect.top,
        mapCenter: { ...mapCenter },
      }
    },
    [mapCenter],
  )

  const handleMouseUp = useCallback(() => setIsDragging(false), [])

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      const px = e.clientX - rect.left
      const py = e.clientY - rect.top

      if (isDragging) {
        const dx = px - dragStart.current.x
        const dy = py - dragStart.current.y
        const startState: MapViewState = {
          mapCenter: dragStart.current.mapCenter,
          zoom,
        }
        const next = applyDrag(startState, { dx, dy }, vp)
        // Clamp lat so the map never shows blank space above/below
        const vMargin = 90 / zoom
        const clampedLat = Math.max(-90 + vMargin, Math.min(90 - vMargin, next.mapCenter.lat))
        syncMapCenter({ lon: next.mapCenter.lon, lat: clampedLat })
        return
      }

      // Hover: rAF throttled
      lastMousePos.current = { px, py }
      if (rafRef.current) return
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0
        const pos = lastMousePos.current
        if (!pos || !elevation) return

        const ll = unproject(pos.px, pos.py)
        // Out of lat range
        if (isNaN(ll.lon) || isNaN(ll.lat) || ll.lat < -90 || ll.lat > 90) {
          onCursorMove?.(null)
          onCellHover?.(null)
          return
        }

        // Elevation lookup
        const ep = lonLatToArrayPixel(ll, mapW, mapH)
        const elev = ep ? (elevation[ep.py * mapW + ep.px] ?? 0) : 0

        onCursorMove?.({
          lon: Math.round(ll.lon * 100) / 100,
          lat: Math.round(ll.lat * 100) / 100,
          elevation: elev,
          elevationM: normalisedToMeters(elev, elevMin, elevMax),
          pixelX: ep?.px ?? 0,
          pixelY: ep?.py ?? 0,
        })

        // KD-tree cell lookup
        if (kdTree) {
          const lonRad = (ll.lon * Math.PI) / 180
          const latRad = (ll.lat * Math.PI) / 180
          const cosLat = Math.cos(latRad)
          const qx = cosLat * Math.cos(lonRad)
          const qy = Math.sin(latRad)
          const qz = cosLat * Math.sin(lonRad)
          const cellId = kdTree.nearest(qx, qy, qz)
          onCellHover?.(cellId >= 0 ? cellId : null)
        }
      })
    },
    [elevation, isDragging, zoom, mapCenter, vp, mapW, mapH, elevMin, elevMax,
     onCursorMove, onCellHover, kdTree],
  )

  // --- Zoom ---
  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault()
      const factor = e.deltaY > 0 ? 0.9 : 1.1
      const newZoom = Math.max(1, Math.min(MAX_ZOOM, zoomRef.current * factor))
      syncZoom(newZoom)
    },
    [],
  )

  // --- Click ---
  // Ctrl+click (single) → toggle cell without replacing other selections.
  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      const ctrl = e.ctrlKey || e.metaKey
      const isTouch = (e.nativeEvent as PointerEvent)?.pointerType === 'touch' ||
        (typeof navigator !== 'undefined' && navigator.maxTouchPoints > 0)
      // Plain click pans (desktop); a tap selects the cell on touch devices.
      if (!ctrl && !isTouch) return
      if (!kdTree || !onCellClick) return
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      const ll = unproject(e.clientX - rect.left, e.clientY - rect.top)
      if (isNaN(ll.lon) || isNaN(ll.lat) || ll.lat < -90 || ll.lat > 90) return
      const lonRad = (ll.lon * Math.PI) / 180
      const latRad = (ll.lat * Math.PI) / 180
      const cosLat = Math.cos(latRad)
      const cellId = kdTree.nearest(
        cosLat * Math.cos(lonRad), Math.sin(latRad), cosLat * Math.sin(lonRad),
      )
      if (cellId >= 0) {
        onCellClick(cellId, ctrl)
        // A tap fires no mousemove, so update cursor/hover explicitly.
        const ep = lonLatToArrayPixel(ll, mapW, mapH)
        const elev = ep && elevation ? (elevation[ep.py * mapW + ep.px] ?? 0) : 0
        onCursorMove?.({
          lon: Math.round(ll.lon * 100) / 100,
          lat: Math.round(ll.lat * 100) / 100,
          elevation: elev,
          elevationM: normalisedToMeters(elev, elevMin, elevMax),
          pixelX: ep?.px ?? 0,
          pixelY: ep?.py ?? 0,
        })
        onCellHover?.(cellId)
      }
    },
    [kdTree, unproject, onCellClick, elevation, elevMin, elevMax, mapW, mapH, onCursorMove, onCellHover],
  )

  const handleDoubleClick = useCallback(
    (e: React.MouseEvent) => {
      if (!kdTree || !onCellClick) return
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      const ll = unproject(
        e.clientX - rect.left,
        e.clientY - rect.top,
      )
      // Out of lat range — ignore
      if (isNaN(ll.lon) || isNaN(ll.lat) || ll.lat < -90 || ll.lat > 90) return
      const lonRad = (ll.lon * Math.PI) / 180
      const latRad = (ll.lat * Math.PI) / 180
      const cosLat = Math.cos(latRad)
      const qx = cosLat * Math.cos(lonRad)
      const qy = Math.sin(latRad)
      const qz = cosLat * Math.sin(lonRad)
      const cellId = kdTree.nearest(qx, qy, qz)
      if (cellId >= 0) onCellClick(cellId, e.ctrlKey || e.metaKey)
    },
    [kdTree, unproject, onCellClick],
  )

  // --- Callback effect ---
  useEffect(() => {
    onZoomChange?.(zoom)
    onViewStateChange?.({
      mapCenter,
      zoom,
      containerWidth: containerSize.width,
      containerHeight: containerSize.height,
    })
  }, [zoom, mapCenter, containerSize, onZoomChange, onViewStateChange])

  // --- Cleanup on leave ---
  const handleMouseLeave = useCallback(() => {
    handleMouseUp()
    if (rafRef.current) { cancelAnimationFrame(rafRef.current); rafRef.current = 0 }
    onCursorMove?.(null)
    onCellHover?.(null)
  }, [handleMouseUp, onCursorMove, onCellHover])

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full overflow-hidden bg-[#0a0a1a] rounded-lg select-none"
      style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
      onMouseMove={handleMouseMove}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
      onMouseLeave={handleMouseLeave}
    >
      <canvas ref={canvasRef} className="absolute inset-0" style={{ background: '#0a0a1a' }} />

      {isRendering && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-[#0a0a1a]/70">
          <div className="text-gray-400 text-sm animate-pulse">rendering...</div>
        </div>
      )}

      {/* Cell hover/selection highlights — SVG overlay (never baked into the texture,
          (Equirectangular previously baked these into the GPU texture; the SVG
          overlay avoids a full texture re-bake on every hover.) */}
      <MapSvgOverlay
        viewWidth={containerSize.width}
        viewHeight={containerSize.height}
        project={project}
        zoom={zoom}
        panWrapOffset={0}
        voronoiCells={voronoiCells}
        cvtMesh={cvtMesh}
        hoveredCell={hoveredCell}
        selectedCells={selectedCells}
        currentOpacity={layers?.currents ?? 0}
        windOpacity={layers?.winds ?? 0}
        monthlyWindEast={monthlyWindEast}
        monthlyWindNorth={monthlyWindNorth}
        month={month}
        showGraticule={showGraticule}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Local helper (avoids circular dependency with mapCoords)
// ---------------------------------------------------------------------------

function lonLatToArrayPixel(
  ll: LonLat,
  mapW: number,
  mapH: number,
): { px: number; py: number } | null {
  if (ll.lat < -90 || ll.lat > 90) return null
  const wLon = ((ll.lon + 180) % 360 + 360) % 360
  const px = Math.floor((wLon / 360) * mapW) % mapW
  const py = Math.max(0, Math.min(mapH - 1, Math.floor(((90 - ll.lat) / 180) * mapH)))
  return { px, py }
}
