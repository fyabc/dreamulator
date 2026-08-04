/**
 * GlobeViewer — 3D globe visualisation of planet terrain.
 *
 * Renders an equirectangular terrain texture on a sphere inside an
 * R3F Canvas with OrbitControls.  Supports cell hover / selection
 * via raycasting + KD-tree (same pipeline as 2D MapViewer).
 *
 * Interaction:
 *   - Left drag: rotate
 *   - Right drag / Ctrl+drag: pan
 *   - Scroll: zoom
 *   - Hover: blue polygon highlight on sphere
 *   - Ctrl+Double-click: toggle cell selection (yellow polygon)
 *   - Double-click: replace cell selection
 *   - Zoom out far enough → "转入星系视图" transition → onTransition
 */

import { Suspense, useRef, useState, useEffect, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Stars, Text } from '@react-three/drei'
import * as THREE from 'three'

import { sunDirection } from './utils/solar'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SPHERE_RADIUS = 1
const TRANSITION_START_DIST = 4.5
const TRANSITION_END_DIST = 8
const DIST_POLL_MS = 80
const HIGHLIGHT_R = SPHERE_RADIUS * 1.003

// ---------------------------------------------------------------------------
// Types (mirror CVTVertex / CVTRegion from types.ts — transformed by adaptCvtMesh)
// ---------------------------------------------------------------------------

export interface GlobeVertex { id: number; lon: number; lat: number }
export interface GlobeRegion { id: number; vertex_ids: number[] }

interface GlobeViewerProps {
  texture: THREE.Texture | null
  /** Layer-composite pass (useGPUTerrain) — called once per frame before the
   *  scene renders; refreshes the shared composited texture when dirty. */
  renderComposite?: (renderer: THREE.WebGLRenderer) => void
  onTransition?: () => void
  transitionLabel?: string
  onCellHover?: (lon: number, lat: number) => void
  onCellClick?: (lon: number, lat: number, ctrlKey: boolean) => void
  /** Called when the pointer leaves the globe surface. */
  onHoverOut?: () => void
  /** Called with current camera distance (planet radii). */
  onDistanceChange?: (dist: number) => void
  /** CVT vertices (lon/lat). */
  vertices?: GlobeVertex[]
  /** CVT regions (cell → vertex IDs). */
  regions?: GlobeRegion[]
  /** Currently hovered cell ID (blue highlight). */
  hoveredCellId?: number | null
  /** Selected cell IDs (yellow highlight). */
  selectedCellIds?: Set<number>
  /** Sun longitude in degrees (0 = noon at prime meridian). */
  sunLongitudeDeg?: number
  /** Solar declination (subsolar latitude) in degrees — varies with season. */
  solarDeclinationDeg?: number
  /** Enable directional sun lighting (day/night terminator). Off = evenly lit. */
  dayNight?: boolean
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// sphereToLonLat removed — UV-based lookup used instead (matches texture mapping).
// Old: lon = atan2(z, x), lat = asin(y). This gave 3D positions that don't match
// the equirectangular texture UV mapping on SphereGeometry.

// ---------------------------------------------------------------------------
// SunLight — directional light positioned by sun longitude + declination
// ---------------------------------------------------------------------------

const SUN_DIST = 8
const SUN_INTENSITY = 1.2

/**
 * Directional light aimed from the subsolar point. The sun longitude drives the
 * diurnal (day/night) rotation; the solar declination — derived from the season
 * and axial tilt upstream — tilts the terminator so the poles get midnight-sun
 * / polar-night behaviour across the year.
 */
function SunLight({ sunLongitudeDeg = 0, solarDeclinationDeg = 0 }: { sunLongitudeDeg?: number; solarDeclinationDeg?: number }) {
  const lightPos = useMemo(() => {
    const [x, y, z] = sunDirection(sunLongitudeDeg, solarDeclinationDeg)
    return [x * SUN_DIST, y * SUN_DIST, z * SUN_DIST] as [number, number, number]
  }, [sunLongitudeDeg, solarDeclinationDeg])

  return <directionalLight position={lightPos} intensity={SUN_INTENSITY} />
}

// ---------------------------------------------------------------------------
// Graticule
// ---------------------------------------------------------------------------

const GRID_STEP = 30
const GRID_R = SPHERE_RADIUS * 1.003

function Graticule() {
  const lines = useMemo(() => {
    const result: { points: [number, number, number][]; key: string }[] = []

    for (let lat = -90 + GRID_STEP; lat < 90; lat += GRID_STEP) {
      const phi = THREE.MathUtils.degToRad(lat)
      const r = GRID_R * Math.cos(phi)
      const y = GRID_R * Math.sin(phi)
      const pts: [number, number, number][] = []
      for (let i = 0; i <= 128; i++) {
        const theta = (i / 128) * Math.PI * 2
        pts.push([r * Math.cos(theta), y, r * Math.sin(theta)])
      }
      result.push({ points: pts, key: `lat-${lat}` })
    }

    for (let lon = -180; lon < 180; lon += GRID_STEP) {
      const theta = THREE.MathUtils.degToRad(lon)
      const pts: [number, number, number][] = []
      for (let i = 0; i <= 128; i++) {
        const phi = (i / 128) * Math.PI
        const r = GRID_R * Math.sin(phi)
        const y = GRID_R * Math.cos(phi)
        pts.push([r * Math.cos(theta), y, r * Math.sin(theta)])
      }
      result.push({ points: pts, key: `lon-${lon}` })
    }
    return result
  }, [])

  return (
    <group>
      {lines.map(({ points, key }) => (
        <line key={key}>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              array={new Float32Array(points.flat())}
              count={points.length} itemSize={3}
            />
          </bufferGeometry>
          <lineBasicMaterial color="rgba(255,255,255,0.12)" transparent opacity={0.25} depthTest />
        </line>
      ))}
    </group>
  )
}

// ---------------------------------------------------------------------------
// Polar axis
// ---------------------------------------------------------------------------

const AXIS_R = SPHERE_RADIUS * 1.08

function PolarAxis() {
  const axisPoints = useMemo(() => new Float32Array([0, -AXIS_R, 0, 0, AXIS_R, 0]), [])
  return (
    <group>
      <line>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" array={axisPoints} count={2} itemSize={3} />
        </bufferGeometry>
        <lineBasicMaterial color="#444466" transparent opacity={0.5} />
      </line>
      <mesh position={[0, AXIS_R, 0]}>
        <coneGeometry args={[0.025, 0.08, 8, 4]} />
        <meshBasicMaterial color="#e53935" />
      </mesh>
      <Text position={[0, AXIS_R + 0.1, 0]} fontSize={0.12} color="#e53935" anchorX="center" anchorY="middle" font={undefined}>N</Text>
      <mesh position={[0, -AXIS_R, 0]} rotation={[Math.PI, 0, 0]}>
        <coneGeometry args={[0.025, 0.08, 8, 4]} />
        <meshBasicMaterial color="#42a5f5" />
      </mesh>
      <Text position={[0, -AXIS_R - 0.1, 0]} fontSize={0.12} color="#42a5f5" anchorX="center" anchorY="middle" font={undefined}>S</Text>
    </group>
  )
}

// ---------------------------------------------------------------------------
// Cell polygon highlight
// ---------------------------------------------------------------------------

interface CellPolygonProps {
  vertices: GlobeVertex[]
  region: GlobeRegion
  color: string
  opacity?: number
}

/** Renders a single Voronoi cell as a coloured polygon patch on the sphere. */
function CellPolygon({ vertices, region, color, opacity = 0.55 }: CellPolygonProps) {
  const geometry = useMemo(() => {
    const vids = region.vertex_ids
    if (!vids || vids.length < 3) return null

    // vertices are {id, lon, lat} — build lookup and convert to 3D
    const vLookup = new Map<number, GlobeVertex>()
    for (const v of vertices) vLookup.set(v.id, v)

    const pts3D: [number, number, number][] = []
    for (const vid of vids) {
      const v = vLookup.get(vid)
      if (!v) continue
      const phi = THREE.MathUtils.degToRad(v.lat)
      const theta = THREE.MathUtils.degToRad(v.lon)
      const cosLat = Math.cos(phi)
      // Negate z to match SphereGeometry UV mapping:
      // texture pixel (lon,lat) displays at 3D position (cos*cos, sin, -cos*sin)
      pts3D.push([cosLat * Math.cos(theta), Math.sin(phi), -cosLat * Math.sin(theta)])
    }

    if (pts3D.length < 3) return null

    const scaled = pts3D.map(([x, y, z]) => {
      const len = Math.sqrt(x * x + y * y + z * z)
      return [x / len * HIGHLIGHT_R, y / len * HIGHLIGHT_R, z / len * HIGHLIGHT_R] as const
    })

    const positions: number[] = []
    for (let i = 1; i < scaled.length - 1; i++) {
      positions.push(...scaled[0], ...scaled[i], ...scaled[i + 1])
    }

    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
    geo.computeVertexNormals()
    return geo
  }, [vertices, region])

  if (!geometry) return null

  return (
    <mesh geometry={geometry} renderOrder={1}>
      <meshBasicMaterial
        color={color} transparent opacity={opacity}
        depthTest depthWrite={false} side={THREE.DoubleSide}
        polygonOffset polygonOffsetFactor={-2} polygonOffsetUnits={-2}
      />
    </mesh>
  )
}

// ---------------------------------------------------------------------------
// Scene
// ---------------------------------------------------------------------------

interface GlobeSceneProps {
  texture: THREE.Texture | null
  renderComposite?: (renderer: THREE.WebGLRenderer) => void
  distanceRef: React.MutableRefObject<number>
  onCellHover?: (lon: number, lat: number) => void
  onCellClick?: (lon: number, lat: number, ctrlKey: boolean) => void
  onHoverOut?: () => void
  vertices?: GlobeVertex[]
  regions?: GlobeRegion[]
  hoveredCellId?: number | null
  selectedCellIds?: Set<number>
  sunLongitudeDeg?: number
  solarDeclinationDeg?: number
  dayNight?: boolean
}

// North-pole fly animation duration (ms)
const NORTH_ANIM_DURATION = 600
// Default view: camera on +Z axis, north pole (+Y) = top of screen
const NORTH_VIEW_POS = new THREE.Vector3(0, 0, 2.8)
const NORTH_VIEW_TARGET = new THREE.Vector3(0, 0, 0)

interface NorthAnimState {
  startTime: number
  startPos: THREE.Vector3
  startTarget: THREE.Vector3
}

function GlobeScene({
  texture, renderComposite, distanceRef, onCellHover, onCellClick, onHoverOut,
  vertices, regions, hoveredCellId, selectedCellIds,
  sunLongitudeDeg, solarDeclinationDeg, dayNight,
}: GlobeSceneProps) {
  const controlsRef = useRef<any>(null)
  const northAnimRef = useRef<NorthAnimState | null>(null)

  // Refresh the composited layer texture before the globe renders it
  // (negative priority → runs ahead of the default useFrame subscribers).
  useFrame(({ gl }) => { renderComposite?.(gl) }, -1)

  useFrame(({ camera }) => { distanceRef.current = camera.position.length() })

  // Smooth camera animation (north-pole fly)
  useFrame(({ camera }) => {
    const anim = northAnimRef.current
    if (!anim) return
    const controls = controlsRef.current
    if (!controls) return

    const elapsed = performance.now() - anim.startTime
    const t = Math.min(1, elapsed / NORTH_ANIM_DURATION)
    const ease = 1 - (1 - t) ** 3

    camera.position.lerpVectors(anim.startPos, NORTH_VIEW_POS, ease)
    controls.target.lerpVectors(anim.startTarget, NORTH_VIEW_TARGET, ease)
    controls.update()

    if (t >= 1) northAnimRef.current = null
  })

  // Keyboard shortcut: N → reset to default view (north pole = top of screen)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== 'n' && e.key !== 'N') return
      if (e.ctrlKey || e.metaKey || e.altKey) return
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      const controls = controlsRef.current
      if (!controls) return
      const camera = controls.object as THREE.Camera

      northAnimRef.current = {
        startTime: performance.now(),
        startPos: camera.position.clone(),
        startTarget: controls.target.clone(),
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // Build region lookup: cellId → region
  const regionMap = useMemo(() => {
    const m = new Map<number, GlobeRegion>()
    if (regions) for (const r of regions) m.set(r.id, r)
    return m
  }, [regions])

  const hasPolyData = !!(vertices && vertices.length && regions && regions.length)

  const HoverHighlight = hoveredCellId != null && hasPolyData && regionMap.has(hoveredCellId) && (
    <CellPolygon vertices={vertices!} region={regionMap.get(hoveredCellId)!} color="#4da6ff" opacity={0.5} />
  )

  const SelectionHighlights = selectedCellIds && hasPolyData && [...selectedCellIds]
    .filter((id) => regionMap.has(id))
    .map((id) => (
      <CellPolygon key={`sel-${id}`} vertices={vertices!} region={regionMap.get(id)!} color="#f0c040" opacity={0.55} />
    ))

  return (
    <>
      <Stars radius={50} depth={30} count={2000} factor={4} saturation={0} fade speed={0.2} />
      <ambientLight intensity={dayNight ? 0.25 : 1.0} />
      {dayNight && (
        <SunLight sunLongitudeDeg={sunLongitudeDeg} solarDeclinationDeg={solarDeclinationDeg} />
      )}

      {/* Planet sphere with pointer events */}
      <mesh
        onPointerMove={(e: any) => {
          // Use UV coordinates to match the texture's equirectangular mapping.
          // This ensures the hovered cell matches the displayed koppen/terrain color.
          const uv = e.uv as { x: number; y: number } | undefined
          if (uv) {
            const lon = uv.x * 360 - 180
            const lat = uv.y * 180 - 90
            onCellHover?.(lon, lat)
          }
        }}
        onPointerOut={() => onHoverOut?.()}
        onDoubleClick={(e: any) => {
          const uv = e.uv as { x: number; y: number } | undefined
          if (uv) {
            const lon = uv.x * 360 - 180
            const lat = uv.y * 180 - 90
            const ctrl = !!(e.nativeEvent as MouseEvent)?.ctrlKey || !!(e.nativeEvent as MouseEvent)?.metaKey
            onCellClick?.(lon, lat, ctrl)
          }
        }}
      >
        <sphereGeometry args={[SPHERE_RADIUS, 64, 32]} />
        {texture ? (
          <meshStandardMaterial map={texture} roughness={0.9} metalness={0.05} />
        ) : (
          <meshStandardMaterial color="#4488aa" roughness={0.8} metalness={0.1} />
        )}
      </mesh>

      {/* Cell polygon highlights */}
      {HoverHighlight}
      {SelectionHighlights}

      <Graticule />
      <PolarAxis />

      {/* Atmosphere shell */}
      <mesh scale={1.015}>
        <sphereGeometry args={[SPHERE_RADIUS, 48, 24]} />
        <meshBasicMaterial color={new THREE.Color(0.4, 0.6, 1.0)} transparent opacity={0.08}
          side={THREE.BackSide} depthWrite={false} />
      </mesh>

      <OrbitControls ref={controlsRef} enableDamping dampingFactor={0.08}
        minDistance={SPHERE_RADIUS * 1.2} maxDistance={TRANSITION_END_DIST}
        maxPolarAngle={Math.PI} target={[0, 0, 0]}
        zoomSpeed={0.8} />
    </>
  )
}

// ---------------------------------------------------------------------------
// Transition overlay
// ---------------------------------------------------------------------------

function TransitionPrompt({ progress, label }: { progress: number; label: string }) {
  if (progress <= 0) return null
  const pct = Math.round(progress * 100)
  return (
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 pointer-events-none">
      <div className="flex flex-col items-center gap-2">
        <span className="text-xs text-neon-cyan/80 tracking-wider animate-pulse">{label}</span>
        <div className="w-48 h-1.5 rounded-full bg-white/10 overflow-hidden">
          <div className="h-full rounded-full bg-gradient-to-r from-neon-cyan/60 to-neon-cyan transition-[width] duration-75 ease-linear"
            style={{ width: `${pct}%` }} />
        </div>
        <span className="text-[10px] text-gray-500 font-mono tabular-nums">{pct}%</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function GlobeViewer({
  texture, renderComposite, onTransition, transitionLabel = '转入星系视图',
  onCellHover, onCellClick, onHoverOut, onDistanceChange,
  vertices, regions, hoveredCellId, selectedCellIds,
  sunLongitudeDeg, solarDeclinationDeg, dayNight,
}: GlobeViewerProps) {
  const distanceRef = useRef(TRANSITION_START_DIST - 1)
  const [progress, setProgress] = useState(0)
  const navigateRef = useRef(false)

  useEffect(() => {
    const interval = setInterval(() => {
      const dist = distanceRef.current
      onDistanceChange?.(dist)
      if (dist <= TRANSITION_START_DIST) { setProgress(0); return }
      const p = Math.min(1, (dist - TRANSITION_START_DIST) / (TRANSITION_END_DIST - TRANSITION_START_DIST))
      setProgress(p)
      if (p >= 1 && onTransition && !navigateRef.current) {
        navigateRef.current = true
        setTimeout(() => onTransition(), 300)
      }
      if (p < 0.98) navigateRef.current = false
    }, DIST_POLL_MS)
    return () => clearInterval(interval)
  }, [onTransition, onDistanceChange])

  useEffect(() => { setProgress(0); navigateRef.current = false }, [texture])

  return (
    <div className="w-full relative" style={{ height: '70vh', minHeight: '500px' }}>
      <TransitionPrompt progress={progress} label={transitionLabel} />
      <Suspense fallback={<div className="flex items-center justify-center h-full text-gray-500">加载 3D 地球...</div>}>
        <Canvas
          camera={{ position: [0, 0, 2.8], fov: 40 }}
          gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.0 }}
          style={{ background: '#030308', borderRadius: '0.75rem' }}
        >
          <GlobeScene
            texture={texture} renderComposite={renderComposite} distanceRef={distanceRef}
            onCellHover={onCellHover} onCellClick={onCellClick}
            onHoverOut={onHoverOut}
            vertices={vertices} regions={regions}
            hoveredCellId={hoveredCellId} selectedCellIds={selectedCellIds}
            sunLongitudeDeg={sunLongitudeDeg} solarDeclinationDeg={solarDeclinationDeg}
            dayNight={dayNight}
          />
        </Canvas>
      </Suspense>
    </div>
  )
}
