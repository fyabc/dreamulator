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
import useTerrainTexture, { type ColorMode } from '../../viewers/map/TerrainPlane'
import useCellIdMap from '../../viewers/map/useCellIdMap'
import useGPUTerrain from '../../viewers/map/useGPUTerrain'
import useRafCoalesced from '../../viewers/map/useRafCoalesced'
import { useGPUReproject, type ReprojectableProjection } from '../../viewers/map/gpuReproject'
import MapSvgOverlay from './MapSvgOverlay'
import {
  normalisedToMeters,
  projectForward,
  projectInverse,
  type ProjectionType,
} from '../../viewers/map/utils/projection'
import {
  lonLatToScreen,
  screenToLonLat,
  applyDrag,
  type MapViewState,
  type LonLat,
  type Viewport,
} from '../../viewers/map/utils/mapCoords'
import type {
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
  projection?: ProjectionType // equirectangular (GPU) | mollweide | robinson (CPU)
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
  /** Force the legacy CPU reprojection for Mollweide/Robinson (?reproject=cpu).
   *  Debug / A-B comparison only — NOT a no-GPU fallback (display needs WebGL). */
  forceCpuReproject?: boolean
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
  projection = 'equirectangular',
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
  forceCpuReproject = false,
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

  // --- GPU / CPU materials ---
  // Mollweide/Robinson are reprojected on the GPU by inverse-warping the baked
  // equirectangular texture (gpuReproject.ts).  Cell hover/selection highlights
  // are drawn by the SVG overlay for ALL projections (not baked into the
  // texture), so hovering never triggers a texture re-bake.
  const reprojectable = projection === 'mollweide' || projection === 'robinson'

  // Opacity sliders fire many events per frame; coalesce so the composite
  // pass (and any data-driven re-bake) runs at most once per animation frame.
  const renderLayers = useRafCoalesced(layers)

  const { material: gpuMaterial, texture: gpuTexture, renderComposite: gpuRenderComposite } = useGPUTerrain({
    elevation, width: mapW, height: mapH, seaLevel,
    elevMinM: elevMin, elevMaxM: elevMax,
    layers: renderLayers, cvtMesh, cellIdMap,
    flipHorizontal: false,  // PlaneGeometry, not SphereGeometry
    sunLonRad, sunDecRad, dayNight: dayNightNum,
  })

  // Ref so the (stable) rAF render loop always sees the current callback.
  const gpuCompositeRef = useRef(gpuRenderComposite)
  gpuCompositeRef.current = gpuRenderComposite

  // GPU reprojection (Mollweide/Robinson): inverse-warp the baked equirect
  // texture.  useGPUReproject manages the material and keeps the sun uniforms
  // updated reactively, so the day/night slider never recompiles the shader.
  // Sample whatever the hook exposes as the current colour source: the FBO
  // composite while overlays are active, otherwise the plain base texture.
  // (The FBO is only rendered while overlays are active, so sampling it in the
  // no-overlay case would read a stale target.)
  const reprojectSource = gpuTexture
  const gpuReprojectActive = reprojectable && !forceCpuReproject
  const reprojectMaterial = useGPUReproject(
    gpuReprojectActive ? (projection as ReprojectableProjection) : null,
    reprojectSource,
    sunLonRad,
    sunDecRad,
    dayNightNum,
  )
  const gpuReprojectOn = gpuReprojectActive && reprojectMaterial !== null

  const cpuTexture = useTerrainTexture({
    elevation, width: mapW, height: mapH, seaLevel,
    elevMinM: elevMin, elevMaxM: elevMax,
    colorMode: (renderLayers?.landsea ?? 0) > 0 ? 'landsea' : 'terrain', cvtMesh, cellIdMap,
    projection,
    sunLonRad, sunDecRad, dayNight: dayNightNum,
    // CPU texture is only needed for the CPU paths: Robinson always, and
    // Mollweide when GPU reproject is disabled (?reproject=cpu).  Equirectangular
    // always uses the GPU path.
    enabled: projection !== 'equirectangular' && !gpuReprojectOn,
  })
  const useGPU = gpuMaterial !== null && projection === 'equirectangular'
  const terrainTexture = useGPU || gpuReprojectOn ? null : cpuTexture

  // --- WebGL init ---
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const renderer = new WebGLRenderer({ canvas, antialias: true })
    // Disable built-in sRGB output encoding so that MeshBasicMaterial (CPU path)
    // and ShaderMaterial (GPU path) both pass pre-encoded sRGB values straight
    // to the framebuffer.  Without this, MeshBasicMaterial applies linearToSRGB
    // on top of our already-sRGB data, washing out Mollweide/Robinson colours.
    renderer.outputColorSpace = THREE.LinearSRGBColorSpace
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
    } else if (gpuReprojectOn) {
      mat = reprojectMaterial
    } else if (terrainTexture) {
      mat = new THREE.MeshBasicMaterial({
        map: terrainTexture,
        side: THREE.DoubleSide,
        transparent: projection !== 'equirectangular', // alpha edges for Robinson
      })
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

    // Ghost meshes only for equirectangular (cylindrical projection wraps horizontally).
    // Non-equirectangular projections (Mollweide, Robinson) have natural edges
    // — ghost meshes would create artificial left-right connection.
    if (projection === 'equirectangular') {
      for (const dir of [-1, 1]) {
        const g = new THREE.Mesh(geo, useGPU
          ? gpuMaterial!
          : new THREE.MeshBasicMaterial({ map: terrainTexture!, side: THREE.DoubleSide }))
        g.rotation.x = -Math.PI / 2
        scene.add(g)
        if (dir === -1) ghostLeftRef.current = g
        else ghostRightRef.current = g
      }
    } else {
      ghostLeftRef.current = null
      ghostRightRef.current = null
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
  }, [webgpuReady, terrainTexture, useGPU, gpuReprojectOn, reprojectMaterial, gpuMaterial, projection, mapW, mapH, containerSize])

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
      if (projection === 'equirectangular') {
        // Use ref for zoom to stay in sync with render loop (no 1-frame lag)
        return lonLatToScreen({ lon, lat }, { mapCenter: mapCenterRef.current, zoom: zoomRef.current }, vp)
      }
      // Non-equirectangular: refs for pan/zoom (instant sync), state for size
      const mc = mapCenterRef.current
      const z = zoomRef.current
      const pc = projectForward(projection, mc.lon, mc.lat)
      const { nx, ny } = projectForward(projection, lon, lat)
      const x = (nx - pc.nx) * containerSize.width * z + containerSize.width / 2
      const y = (ny - pc.ny) * containerSize.height * z + containerSize.height / 2
      return { x, y }
    },
    // Refs used inside for accuracy (no 1-frame lag), but mapCenter/zoom
    // in deps to trigger SVG re-render on pan.
    [projection, vp, mapCenter, zoom, containerSize],
  )

  // --- Reverse projection (screen → geographic) ---
  const unproject = useCallback(
    (px: number, py: number) => {
      if (projection === 'equirectangular') {
        return screenToLonLat(px, py, { mapCenter: mapCenterRef.current, zoom: zoomRef.current }, vp)
      }
      const mc = mapCenterRef.current
      const z = zoomRef.current
      const pc = projectForward(projection, mc.lon, mc.lat)
      const nx = (px - containerSize.width / 2) / (containerSize.width * z) + pc.nx
      const ny = (py - containerSize.height / 2) / (containerSize.height * z) + pc.ny
      return projectInverse(projection, nx, ny)
    },
    [projection, vp, mapCenter, zoom, containerSize],
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
        if (projection === 'equirectangular') {
          mesh.position.x = -(mc.lon / 360) * visW
          mesh.position.z = (mc.lat / 180) * BASE_VIS_H
        } else {
          const pc = projectForward(projection, mc.lon, mc.lat)
          mesh.position.x = -(pc.nx - 0.5) * visW
          mesh.position.z = -(pc.ny - 0.5) * BASE_VIS_H
        }

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
    // `projection` must be live: the loop positions the mesh per-projection, so a
    // stale capture (e.g. always 'equirectangular') mis-positions Mollweide/Robinson
    // vertically (linear-in-lat instead of the projection's non-linear ny).
  }, [projection])

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
        // Non-cylindrical projections: clamp in projection space (nonlinear lon→nx)
        let clampedLon = next.mapCenter.lon
        if (projection !== 'equirectangular') {
          const nxt = projectForward(projection, next.mapCenter.lon, clampedLat)
          const nMargin = 0.5 / zoom
          const clampedNx = Math.max(nMargin, Math.min(1 - nMargin, nxt.nx))
          if (Math.abs(clampedNx - nxt.nx) > 1e-10) {
            const back = projectInverse(projection, clampedNx, nxt.ny)
            clampedLon = back.lon
          }
        }
        syncMapCenter({ lon: clampedLon, lat: clampedLat })
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
        // Outside projection boundary (non-equirectangular) or out of lat range
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
          elevationM: Math.round(normalisedToMeters(elev, elevMin, elevMax)),
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
  const handleDoubleClick = useCallback(
    (e: React.MouseEvent) => {
      if (!kdTree || !onCellClick) return
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      const ll = unproject(
        e.clientX - rect.left,
        e.clientY - rect.top,
      )
      // Outside projection boundary (non-equirectangular) — ignore
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
      onDoubleClick={handleDoubleClick}
      onMouseLeave={handleMouseLeave}
    >
      <canvas ref={canvasRef} className="absolute inset-0" style={{ background: '#0a0a1a' }} />

      {isRendering && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-[#0a0a1a]/70">
          <div className="text-gray-400 text-sm animate-pulse">rendering...</div>
        </div>
      )}

      {/* Cell hover/selection highlights — SVG overlay for all projections.
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
