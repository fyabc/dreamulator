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

import { meshTextureDimensions, type TerrainSource } from '../../viewers/map/elevationSource'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { WebGLRenderer } from 'three'
import useCellIdMap from '../../viewers/map/useCellIdMap'
import useGPUTerrain from '../../viewers/map/useGPUTerrain'
import { useTranslation } from 'react-i18next'
import type { TrialTerrain } from '../../playground/temperaturePreview'
import { GRID_H, GRID_W } from '../../playground/temperatureDraft'
import useRafCoalesced from '../../viewers/map/useRafCoalesced'
import MapSvgOverlay from './MapSvgOverlay'
import FlowParticles from './FlowParticles'
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
  PointProjector,
  VoronoiCell,
  CVTMesh,
} from '../../viewers/map/types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface MapViewerProps {
  metadata: MapMetadata | null
  elevation: Float32Array | null
  terrainSource?: TerrainSource
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
  /** Fills a form with the clicked point (region centre). Takes precedence over
   *  cell selection while set, including on plain clicks and taps. */
  onPickPoint?: (point: LonLat) => void
  /** Right-click clears the pinned selection (easier than double-clicking the
   *  same cell again when the map is zoomed out). */
  onClearSelection?: () => void
  /** Fired once the first frame with the baked terrain has been presented;
   *  the page keeps its loading placeholder up until then. */
  onReady?: () => void
  /** Phone layout: skip idle pre-bakes that would hold extra 8 MB textures. */
  lowMemory?: boolean
  /** Bump to restore the initial centre and zoom. */
  viewResetRevision?: number
  hoveredCell: number | null
  selectedCells: Set<number>
  regionBoundary?: readonly LonLat[] | null
  regionFocus?: LonLat | null
  regionMoveRevision?: number
  /** Subsolar longitude in degrees (day/night overlay). */
  sunLongitudeDeg?: number
  /** Solar declination in degrees (day/night overlay). */
  solarDeclinationDeg?: number
  /** Enable the day/night overlay. */
  dayNight?: boolean
  trialTemperature?: THREE.DataTexture | null
  trialTerrain?: TrialTerrain | null
  scalarThematic?: import('../../viewers/map/useMonthlyClimate').ScalarTexture | null
  koppenTexture?: THREE.DataTexture | null
  /** UCC classification thematic texture (UCC-01 step 4a), baked by the caller
   *  from `bakeUccLayer`; null when the yearly file lacks the fields. */
  uccTexture?: THREE.DataTexture | null
  /** Monthly wind arrows (tech debt 24): N×12 components in mesh-cell order. */
  monthlyWindEast?: Float32Array | null
  monthlyWindNorth?: Float32Array | null
  month?: number
  /** Render wind/current layers as particle trails instead of arrows. */
  particleMode?: boolean
  /** Planet radius (metres) for the particle integrator. */
  planetRadiusM?: number
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
  terrainSource = 'mesh',
  voronoiCells,
  cvtMesh,
  layers,
  onZoomChange,
  onViewStateChange,
  onCursorMove,
  onCellHover,
  onCellClick,
  onPickPoint,
  onClearSelection,
  onReady,
  lowMemory = false,
  viewResetRevision = 0,
  hoveredCell,
  selectedCells,
  regionBoundary,
  regionFocus,
  regionMoveRevision,
  sunLongitudeDeg = 0,
  solarDeclinationDeg = 0,
  dayNight = false,
  trialTemperature = null,
  trialTerrain = null,
  scalarThematic = null,
  koppenTexture = null,
  uccTexture = null,
  monthlyWindEast = null,
  monthlyWindNorth = null,
  month = 0,
  particleMode = false,
  planetRadiusM,
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
  const [mapCenter, setMapCenter] = useState<LonLat>(() => regionFocus ?? { lon: 0, lat: 0 })
  const [zoom, setZoomState] = useState(1)

  // --- Refs for render loop (updated synchronously with state) ---
  const mapCenterRef = useRef(mapCenter)
  const zoomRef = useRef(1)
  const containerRef2 = useRef({ width: 800, height: 400 })
  /** Allocation-free projector handed to the particle overlay. */
  const mapPointProjectRef = useRef<PointProjector | null>(null)

  // Sync helpers: update BOTH state and ref immediately
  const syncMapCenter = useCallback((mc: LonLat) => {
    mapCenterRef.current = mc
    setMapCenter(mc)
  }, [])
  const syncZoom = useCallback((z: number) => {
    zoomRef.current = z
    setZoomState(z)
  }, [])
  useEffect(() => {
    if (regionFocus) syncMapCenter(regionFocus)
  }, [regionFocus, regionMoveRevision, syncMapCenter])
  // Reset button: return to the initial centre and zoom, like a fresh load.
  const resetRevisionRef = useRef(0)
  useEffect(() => {
    if (resetRevisionRef.current === viewResetRevision) return
    resetRevisionRef.current = viewResetRevision
    syncMapCenter(regionFocus ?? { lon: 0, lat: 0 })
    syncZoom(1)
  }, [viewResetRevision, regionFocus, syncMapCenter, syncZoom])

  // Map dimensions
  const mapW = metadata?.width ?? 2048
  const mapH = metadata?.height ?? 1024
  const seaLevel = metadata?.sea_level_m ?? 0.0
  const elevMin = metadata?.elevation_min_m ?? -11000
  const elevMax = metadata?.elevation_max_m ?? 9000


  // Cell-ID map and layer bakes.  On phones both are capped at 2048 px wide
  // (same cap as usePlanetViewState) so the base textures, overlay textures and
  // cell-ID map share one memory budget instead of exceeding the GPU.
  const meshSize = useMemo(() => {
    const size = meshTextureDimensions(metadata)
    if (!lowMemory || size.width <= 2048 || size.width <= 0) return size
    return { width: 2048, height: Math.max(1, Math.round(size.height * 2048 / size.width)) }
  }, [metadata, lowMemory])
  const cellIdMap = useCellIdMap({ cvtMesh, ...meshSize })

  /** Nearest cell for a geographic point, sampled from the same cell-ID map
   *  that colours the texture.  This replaces the KD-tree: it picks exactly the
   *  cell drawn under the cursor and avoids a ~600 ms idle tree build. */
  const cellAtLonLat = useCallback((lon: number, lat: number): number => {
    if (cellIdMap && meshSize.width > 0 && meshSize.height > 1) {
      const px = Math.max(0, Math.min(meshSize.width - 1,
        Math.round(((lon + 180) / 360) * (meshSize.width - 1))))
      const py = Math.max(0, Math.min(meshSize.height - 1,
        Math.round(((90 - lat) / 180) * (meshSize.height - 1))))
      const id = cellIdMap[py * meshSize.width + px]
      return id === 0xffffffff ? -1 : id
    }
    return -1
  }, [cellIdMap, meshSize.width, meshSize.height])

  // Loading indicator (useEffect avoids rAF in render body, enables cleanup)
  const { t } = useTranslation('map')
  const [isRendering, setIsRendering] = useState(false)
  useEffect(() => {
    setIsRendering(true)
    const rafId = requestAnimationFrame(() => setIsRendering(false))
    return () => cancelAnimationFrame(rafId)
  }, [cellIdMap])

  // First-frame signal for the page's loading gate.  Re-armed whenever the
  // elevation data changes (planet / branch / terrain source switch).
  const onReadyRef = useRef(onReady)
  onReadyRef.current = onReady
  const readyNotified = useRef(false)
  useEffect(() => { readyNotified.current = false }, [elevation])
  /** Set while a finger is on the map; compatibility mouse events emitted for
   *  touch must not run hover hit-testing or wheel handling. */
  const touchActiveRef = useRef(false)

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

  const { material: gpuMaterial, renderComposite: gpuRenderComposite, warmOverlays: gpuWarmOverlays } = useGPUTerrain({
    elevation, width: mapW, height: mapH, seaLevel,
    terrainSource, meshWidth: meshSize.width, meshHeight: meshSize.height,
    elevMinM: elevMin, elevMaxM: elevMax,
    layers: renderLayers, cvtMesh, cellIdMap,
    scalarThematic, koppenTexture,
    uccTexture,
    flipHorizontal: false,  // PlaneGeometry, not SphereGeometry
    sunLonRad, sunDecRad, dayNight: dayNightNum, lowMemory,
    ...(trialTerrain && {
      elevation: trialTerrain.elevation, width: GRID_W, height: GRID_H,
      terrainSource: 'raster', meshWidth: GRID_W, meshHeight: GRID_H,
      seaLevel: trialTerrain.params.seaLevelM, elevMinM: trialTerrain.params.elevMinM, elevMaxM: trialTerrain.params.elevMaxM,
      cvtMesh: null, cellIdMap: null, monthlyTemperature: trialTemperature,
    }),
  })

  // Ref so the (stable) rAF render loop always sees the current callback.
  const gpuCompositeRef = useRef(gpuRenderComposite)
  const gpuWarmRef = useRef(gpuWarmOverlays)
  gpuCompositeRef.current = gpuRenderComposite
  gpuWarmRef.current = gpuWarmOverlays

  // Pre-bake and upload the common overlays while the page is idle: the first
  // temperature/precipitation selection then costs only one composite pass.
  const warmedRef = useRef(false)
  useEffect(() => {
    if (lowMemory || warmedRef.current || !cvtMesh || !cellIdMap) return
    const run = () => {
      if (warmedRef.current) return
      const renderer = rendererRef.current
      if (!renderer) return
      warmedRef.current = true
      // Two callbacks: one overlay bakes + uploads in ~300 ms, and running both
      // in a single idle slice made a 600 ms long task.
      gpuWarmRef.current(renderer, ['temperature'])
      const finish = () => gpuWarmRef.current(renderer, ['precipitation'])
      if (typeof window.requestIdleCallback === 'function') window.requestIdleCallback(finish, { timeout: 8000 })
      else window.setTimeout(finish, 4000)
    }
    const idle = typeof window.requestIdleCallback === 'function'
      ? window.requestIdleCallback(run, { timeout: 4000 }) : undefined
    const timer = idle === undefined ? window.setTimeout(run, 2000) : undefined
    return () => {
      if (idle !== undefined) window.cancelIdleCallback(idle)
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [cvtMesh, cellIdMap, lowMemory])

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

  // Particle projector: screen positions are CSS pixels relative to the view
  // container.  The epoch changes with the view, letting the trail canvas clear
  // on pan/zoom instead of smearing old screen-space segments.
  if (particleMode) {
    const projector = ((lon: number, lat: number, out: { x: number; y: number; edgeFade: number }) => {
      const p = project(lon, lat)
      out.x = p.x
      out.y = p.y
      out.edgeFade = 1
      return true
    }) as PointProjector
    projector.epoch = hashViewKey(
      `${mapCenter.lon}|${mapCenter.lat}|${zoom}|${containerSize.width}x${containerSize.height}`,
    )
    mapPointProjectRef.current = projector
  }

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
        if (!readyNotified.current) {
          readyNotified.current = true
          onReadyRef.current?.()
        }
      }
      rafId = requestAnimationFrame(loop)
    }
    rafId = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(rafId)
  }, [])

  // --- Mouse handlers ---

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (touchActiveRef.current) return
      if (e.button !== 0 && e.button !== 1) return
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      setIsDragging(true)
      mouseDownPosRef.current = { x: e.clientX, y: e.clientY }
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
      if (touchActiveRef.current) return
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

        // Cell lookup (KD-tree on desktop, cell-ID map on phones)
        const cellId = cellIdMap ? cellAtLonLat(ll.lon, ll.lat) : -1
        if (cellIdMap) onCellHover?.(cellId >= 0 ? cellId : null)
        const meshElev = terrainSource === 'mesh' && cellId >= 0 ? voronoiCells[cellId]?.elevation : undefined
        onCursorMove?.({
          lon: Math.round(ll.lon * 100) / 100,
          lat: Math.round(ll.lat * 100) / 100,
          elevation: meshElev == null ? elev : (meshElev - elevMin) / (elevMax - elevMin || 1),
          elevationM: meshElev ?? normalisedToMeters(elev, elevMin, elevMax),
          pixelX: ep?.px ?? 0,
          pixelY: ep?.py ?? 0,
        })
      })
    },
    [elevation, isDragging, zoom, mapCenter, vp, mapW, mapH, elevMin, elevMax,
     onCursorMove, onCellHover, cellIdMap, cellAtLonLat, terrainSource, voronoiCells],
  )

  // --- Touch: single-finger pan + two-finger pinch zoom ---
  // The desktop handlers above only cover mouse input; without these the
  // browser scrolls/zooms the whole page when a finger drags on the canvas.
  const touchRef = useRef<{
    mode: 'pan' | 'pinch'
    startX: number
    startY: number
    startCenter: { lon: number; lat: number }
    startZoom: number
    startDistance: number
    moved: boolean
  } | null>(null)
  const suppressClickRef = useRef(false)
  // Mouse-down position, so a pan that ends with a click does not select or pick.
  const mouseDownPosRef = useRef<{ x: number; y: number } | null>(null)

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return
    suppressClickRef.current = false
    touchActiveRef.current = true
    if (e.touches.length >= 2) {
      const [a, b] = [e.touches[0], e.touches[1]]
      touchRef.current = {
        mode: 'pinch', startX: 0, startY: 0,
        startCenter: { ...mapCenterRef.current }, startZoom: zoomRef.current,
        startDistance: Math.max(1, Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY)),
        moved: true,
      }
      return
    }
    const touch = e.touches[0]
    touchRef.current = {
      mode: 'pan',
      startX: touch.clientX - rect.left, startY: touch.clientY - rect.top,
      startCenter: { ...mapCenterRef.current }, startZoom: zoomRef.current,
      startDistance: 0, moved: false,
    }
  }, [])

  const handleTouchMove = useCallback((e: React.TouchEvent) => {
    const touch = touchRef.current
    if (!touch) return
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) return
    if (touch.mode === 'pinch' && e.touches.length >= 2) {
      const [a, b] = [e.touches[0], e.touches[1]]
      const distance = Math.max(1, Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY))
      const nextZoom = Math.max(1, Math.min(MAX_ZOOM, touch.startZoom * distance / touch.startDistance))
      syncZoom(nextZoom)
      const margin = 90 / nextZoom
      syncMapCenter({
        lon: mapCenterRef.current.lon,
        lat: Math.max(-90 + margin, Math.min(90 - margin, mapCenterRef.current.lat)),
      })
      return
    }
    if (e.touches.length !== 1) return
    const point = e.touches[0]
    const dx = (point.clientX - rect.left) - touch.startX
    const dy = (point.clientY - rect.top) - touch.startY
    if (Math.hypot(dx, dy) > 6) {
      touch.moved = true
      suppressClickRef.current = true
    }
    const next = applyDrag({ mapCenter: touch.startCenter, zoom: touch.startZoom }, { dx, dy }, vp)
    const margin = 90 / touch.startZoom
    syncMapCenter({
      lon: next.mapCenter.lon,
      lat: Math.max(-90 + margin, Math.min(90 - margin, next.mapCenter.lat)),
    })
  }, [syncMapCenter, syncZoom, vp])

  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    if (e.touches.length === 0) {
      touchRef.current = null
      touchActiveRef.current = false
      return
    }
    // One finger lifted after a pinch: continue as a pan with the remaining one.
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect) { touchRef.current = null; return }
    const point = e.touches[0]
    touchActiveRef.current = true
    touchRef.current = {
      mode: 'pan',
      startX: point.clientX - rect.left, startY: point.clientY - rect.top,
      startCenter: { ...mapCenterRef.current }, startZoom: zoomRef.current,
      startDistance: 0, moved: true,
    }
  }, [])

  // --- Zoom (native non-passive wheel listener) ---
  // React attaches wheel listeners passively, so preventDefault() inside an
  // onWheel handler is ignored and logs a console warning; attach our own with
  // { passive: false } so the page does not scroll under the map.
  useEffect(() => {
    const element = containerRef.current
    if (!element) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const factor = event.deltaY > 0 ? 0.9 : 1.1
      syncZoom(Math.max(1, Math.min(MAX_ZOOM, zoomRef.current * factor)))
    }
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => element.removeEventListener('wheel', onWheel)
  }, [syncZoom])

  // --- Click ---
  // Picking mode (region centre) consumes plain clicks and taps; otherwise
  // Ctrl+click (single) toggles a cell without replacing other selections.
  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      if (suppressClickRef.current) { suppressClickRef.current = false; return }
      const start = mouseDownPosRef.current
      mouseDownPosRef.current = null
      // A pan releases with a click on the same element; treat movement as a drag.
      if (start && Math.hypot(e.clientX - start.x, e.clientY - start.y) > 6) return
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      const ll = unproject(e.clientX - rect.left, e.clientY - rect.top)
      if (isNaN(ll.lon) || isNaN(ll.lat) || ll.lat < -90 || ll.lat > 90) return
      const ctrl = e.ctrlKey || e.metaKey
      // Ctrl/Cmd+click keeps its cell-selection meaning, so the "Use selected
      // point" workflow still works while the region form is open.
      if (onPickPoint && !ctrl) {
        onPickPoint({ lon: Math.round(ll.lon * 100) / 100, lat: Math.round(ll.lat * 100) / 100 })
        return
      }
      const isTouch = (e.nativeEvent as PointerEvent)?.pointerType === 'touch' ||
        (typeof navigator !== 'undefined' && navigator.maxTouchPoints > 0)
      // Plain click pans (desktop); a tap selects the cell on touch devices.
      if (!ctrl && !isTouch) return
      if (!cellIdMap && !trialTemperature) return
      const cellId = cellAtLonLat(ll.lon, ll.lat)
      if (cellId >= 0 || trialTemperature) {
        if (cellId >= 0) onCellClick?.(cellId, ctrl)
        // A tap fires no mousemove, so update cursor/hover explicitly.
        const ep = lonLatToArrayPixel(ll, mapW, mapH)
        const elev = ep && elevation ? (elevation[ep.py * mapW + ep.px] ?? 0) : 0
        const meshElev = terrainSource === 'mesh' ? voronoiCells[cellId]?.elevation : undefined
        onCursorMove?.({
          lon: Math.round(ll.lon * 100) / 100,
          lat: Math.round(ll.lat * 100) / 100,
          elevation: meshElev == null ? elev : (meshElev - elevMin) / (elevMax - elevMin || 1),
          elevationM: meshElev ?? normalisedToMeters(elev, elevMin, elevMax),
          pixelX: ep?.px ?? 0,
          pixelY: ep?.py ?? 0,
        })
        onCellHover?.(cellId >= 0 ? cellId : null)
      }
    },
    [cellIdMap, cellAtLonLat, trialTemperature, unproject, onCellClick, onPickPoint, elevation, elevMin, elevMax, mapW, mapH, onCursorMove, onCellHover, terrainSource, voronoiCells],
  )

  const handleDoubleClick = useCallback(
    (e: React.MouseEvent) => {
      if (touchActiveRef.current) return
      if (!cellIdMap || !onCellClick) return
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      const ll = unproject(
        e.clientX - rect.left,
        e.clientY - rect.top,
      )
      // Out of lat range — ignore
      if (isNaN(ll.lon) || isNaN(ll.lat) || ll.lat < -90 || ll.lat > 90) return
      const cellId = cellAtLonLat(ll.lon, ll.lat)
      if (cellId >= 0) onCellClick(cellId, e.ctrlKey || e.metaKey)
    },
    [cellIdMap, cellAtLonLat, unproject, onCellClick],
  )

  /** Right-click clears the selection.  The browser menu is suppressed only
   *  when there is a selection, so right-click elsewhere still behaves
   *  normally. */
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    if (!onClearSelection) return
    if (e.currentTarget === e.target || (e.target as HTMLElement).tagName === 'CANVAS') {
      e.preventDefault()
      onClearSelection()
    }
  }, [onClearSelection])

  // --- Callback effect (throttled: the page re-renders on every update) ---
  const viewPending = useRef<{
    mapCenter: { lon: number; lat: number }
    zoom: number
    containerWidth: number
    containerHeight: number
  } | null>(null)
  const viewTimer = useRef(0)
  const viewLast = useRef(0)
  useEffect(() => {
    viewPending.current = {
      mapCenter, zoom,
      containerWidth: containerSize.width,
      containerHeight: containerSize.height,
    }
    if (viewTimer.current) return
    const flush = () => {
      viewTimer.current = 0
      viewLast.current = performance.now()
      const state = viewPending.current
      if (!state) return
      onZoomChange?.(state.zoom)
      onViewStateChange?.(state)
    }
    const wait = Math.max(0, 120 - (performance.now() - viewLast.current))
    viewTimer.current = window.setTimeout(flush, wait)
  }, [zoom, mapCenter, containerSize, onZoomChange, onViewStateChange])
  useEffect(() => () => {
    // StrictMode remounts run this cleanup; reset the ref as well, or the next
    // mount sees a stale timer id and never schedules another view-state flush.
    if (viewTimer.current) window.clearTimeout(viewTimer.current)
    viewTimer.current = 0
  }, [])

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
      className="relative w-full h-full overflow-hidden bg-[#0a0a1a] rounded-lg select-none touch-none"
      style={{ cursor: isDragging ? 'grabbing' : 'grab' }}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
      onTouchCancel={handleTouchEnd}
      onMouseMove={handleMouseMove}
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
      onContextMenu={handleContextMenu}
      onMouseLeave={handleMouseLeave}
    >
      <canvas ref={canvasRef} className="absolute inset-0" style={{ background: '#0a0a1a' }} />

      {particleMode && !trialTemperature && (
        <>
          <FlowParticles
            projectRef={mapPointProjectRef}
            kind="current"
            cells={voronoiCells}
            opacity={layers?.currents ?? 0}
            planetRadiusM={planetRadiusM}
            cellIdMap={cellIdMap}
            meshWidth={meshSize.width}
            meshHeight={meshSize.height}
            positioning="absolute"
          />
          <FlowParticles
            projectRef={mapPointProjectRef}
            kind="wind"
            cells={voronoiCells}
            opacity={layers?.winds ?? 0}
            monthlyWindEast={monthlyWindEast}
            monthlyWindNorth={monthlyWindNorth}
            month={month}
            planetRadiusM={planetRadiusM}
            positioning="absolute"
          />
        </>
      )}

      {isRendering && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-[#0a0a1a]/70">
          <div className="text-gray-400 text-sm animate-pulse">{t('label.generatingTexture')}</div>
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
        regionBoundary={regionBoundary}
        currentOpacity={particleMode || trialTemperature ? 0 : layers?.currents ?? 0}
        windOpacity={particleMode || trialTemperature ? 0 : layers?.winds ?? 0}
        monthlyWindEast={monthlyWindEast}
        monthlyWindNorth={monthlyWindNorth}
        month={month}
        showGraticule={showGraticule}
      />
    </div>
  )
}

/** FNV-1a hash of the view key (pan/zoom/size) — used as a trail epoch. */
function hashViewKey(key: string): number {
  let h = 2166136261
  for (let i = 0; i < key.length; i++) {
    h = Math.imul(h ^ key.charCodeAt(i), 16777619)
  }
  return h >>> 0
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
