/**
 * StellarSystemViewer — main 3D visualization container.
 *
 * Renders an interactive Three.js scene at **real astronomical proportions**:
 * - All distances in AU (1 scene unit = 1 AU)
 * - Star and planet radii at true scale
 * - Camera supports extreme zoom: from system overview (10 AU)
 *   down to close-up on a single body (0.001 AU)
 *
 * Visibility of sub-pixel bodies is handled by Label components
 * (dot + leader line), not by distorting proportions.
 *
 * Uses logarithmicDepthBuffer to handle the enormous near/far ratio
 * (camera at 10 AU viewing objects at 0.00004 AU radius).
 */

import { useState, useMemo, Suspense, useRef, useCallback } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Stars } from '@react-three/drei'
import * as THREE from 'three'
import StarMesh from './StarMesh'
import PlanetMesh from './PlanetMesh'
import OrbitLine from './OrbitLine'
import HabitableZoneRing from './HabitableZoneRing'
import InfoPanel from './InfoPanel'
import { computeOrbitalPosition } from './utils/scale'
import type { StarData } from './StarMesh'
import type { PlanetData, OrbitalElementsData } from './PlanetMesh'
import type { SelectedBody } from './InfoPanel'

type Vec3 = [number, number, number]

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StellarSystemData {
  name?: string
  stars?: StarData[]
  orbits?: OrbitalElementsData[]
  bodies?: PlanetData[]  // normalized OrbitingBody (moons, asteroids)
}

interface HabitableZoneData {
  [key: string]: unknown
  habitable_zone?: {
    recent_venus_au?: number
    runaway_greenhouse_au?: number
    max_greenhouse_au?: number
    early_mars_au?: number
  }
  habitable_zone_center_au?: number
  condensation_lines?: {
    rock_line_au?: number
    water_snow_line_au?: number
    co2_ice_line_au?: number
    co_snow_line_au?: number
  }
}

interface StellarSystemViewerProps {
  stellar: StellarSystemData | null | undefined
  planets: PlanetData[] | null | undefined
  habitableZones: HabitableZoneData | null | undefined
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildOrbitLookup(orbits: OrbitalElementsData[]): Map<string, OrbitalElementsData> {
  const map = new Map<string, OrbitalElementsData>()
  for (const orbit of orbits) {
    map.set(orbit.body_id, orbit)
  }
  return map
}

/**
 * Resolve absolute 3D positions for all bodies in the system.
 *
 * Handles hierarchical orbits: a moon orbiting a planet has its position
 * computed as planet_position + moon_relative_position.
 * Uses recursive lookup with memoization to resolve chains like
 * star → planet → moon.
 */
function resolvePositions(
  stars: StarData[],
  allBodies: PlanetData[],
  orbitMap: Map<string, OrbitalElementsData>,
): Map<string, Vec3> {
  const positions = new Map<string, Vec3>()
  const ORIGIN: Vec3 = [0, 0, 0]

  // Seed star positions
  for (const star of stars) {
    const pos: Vec3 = star.position
      ? [star.position.x, star.position.y, star.position.z]
      : ORIGIN
    positions.set(star.id, pos)
  }

  /** Recursively resolve a body's absolute position. */
  function resolve(bodyId: string, visited: Set<string>): Vec3 {
    const cached = positions.get(bodyId)
    if (cached) return cached

    // Guard against circular references
    if (visited.has(bodyId)) return ORIGIN
    visited.add(bodyId)

    const orbit = orbitMap.get(bodyId)
    if (!orbit) return ORIGIN

    // Recursively resolve parent position first
    const parentPos = resolve(orbit.parent_id, visited)
    const relative = computeOrbitalPosition(orbit)
    const abs: Vec3 = [
      parentPos[0] + relative[0],
      parentPos[1] + relative[1],
      parentPos[2] + relative[2],
    ]
    positions.set(bodyId, abs)
    return abs
  }

  // Resolve each body (recursion handles parent-first ordering)
  for (const body of allBodies) {
    resolve(body.id, new Set())
  }

  return positions
}

function resolveHZ(hz: HabitableZoneData | null | undefined): HabitableZoneData | null {
  if (!hz) return null
  if (hz.habitable_zone) return hz
  const stars = (hz as Record<string, unknown>).stars
  if (Array.isArray(stars) && stars.length > 0) return stars[0] as HabitableZoneData
  return null
}

/**
 * Compute a good initial camera distance based on the outermost planet orbit.
 */
function computeInitialCameraDistance(
  orbits: OrbitalElementsData[],
): number {
  if (orbits.length === 0) return 3
  const maxAU = Math.max(...orbits.map((o) => o.semi_major_axis_au))
  return Math.max(2, maxAU * 2.2)
}

/**
 * Build a map of body_id → number of satellites orbiting it.
 */
function buildSatelliteCountMap(orbits: OrbitalElementsData[]): Map<string, number> {
  const map = new Map<string, number>()
  for (const orbit of orbits) {
    const count = map.get(orbit.parent_id) ?? 0
    map.set(orbit.parent_id, count + 1)
  }
  return map
}

/**
 * Angular size threshold (radians) below which a child body's label is hidden.
 *
 * When a moon's orbit subtends less than this angle from the camera,
 * its label overlaps the parent's label and is suppressed.
 * ~0.04 rad ≈ 2.3° ≈ 4% of a 50° FOV viewport.
 */
const DECLUTTER_THRESHOLD = 0.04

// ---------------------------------------------------------------------------
// Scale display — shows current view distance in AU
// ---------------------------------------------------------------------------

/**
 * No-op scene component reserved for future in-scene scale bar.
 * Camera distance is displayed via the HTML overlay instead.
 */
function ScaleIndicator() {
  return null
}

// ---------------------------------------------------------------------------
// Scene
// ---------------------------------------------------------------------------

function Scene({
  stellar,
  allBodies,
  positionMap,
  satelliteCountMap,
  orbitMap,
  habitableZones,
  selected,
  onSelect,
  controlsRef,
  onControlsChange,
  focusTargetRef,
  focusedRadiusRef,
}: {
  stellar: StellarSystemData | null | undefined
  allBodies: PlanetData[]
  positionMap: Map<string, Vec3>
  satelliteCountMap: Map<string, number>
  orbitMap: Map<string, OrbitalElementsData>
  habitableZones: HabitableZoneData | null | undefined
  selected: SelectedBody
  onSelect: (body: SelectedBody) => void
  controlsRef: React.MutableRefObject<any>
  onControlsChange: () => void
  focusTargetRef: React.MutableRefObject<THREE.Vector3 | null>
  focusedRadiusRef: React.MutableRefObject<number | null>
}) {
  const orbits = stellar?.orbits ?? []
  const hzData = useMemo(() => resolveHZ(habitableZones), [habitableZones])

  // Label decluttering — hide child labels when angular size is too small
  const [labelVisibility, setLabelVisibility] = useState<Record<string, boolean>>({})
  const prevVisRef = useRef<string>('')
  useFrame(({ camera }) => {
    const next: Record<string, boolean> = {}
    for (const body of allBodies) {
      const orbit = orbitMap.get(body.id)
      if (!orbit) {
        next[body.id] = true
        continue
      }
      const parentPos = positionMap.get(orbit.parent_id)
      if (!parentPos) {
        next[body.id] = true
        continue
      }
      const camPos = camera.position
      const camDist = Math.sqrt(
        (camPos.x - parentPos[0]) ** 2 +
        (camPos.y - parentPos[1]) ** 2 +
        (camPos.z - parentPos[2]) ** 2,
      )
      const angularSize = orbit.semi_major_axis_au / Math.max(camDist, 0.001)
      next[body.id] = angularSize >= DECLUTTER_THRESHOLD
    }
    // Only setState when visibility actually changed (avoids per-frame re-renders)
    const key = JSON.stringify(next)
    if (key !== prevVisRef.current) {
      prevVisRef.current = key
      setLabelVisibility(next)
    }
  })

  // Smoothly fly camera target to focused body each frame,
  // and sync OrbitControls.minDistance with the focused body's radius.
  useFrame(() => {
    const controls = controlsRef.current
    if (!controls) return

    // Dynamic zoom limit: 1.5× the focused body's real radius (AU).
    // Prevents entering large bodies (stars) while allowing close-up on
    // small bodies (asteroids, small moons).  Default covers Sun-sized.
    const focusedR = focusedRadiusRef.current
    controls.minDistance = focusedR != null ? focusedR * 1.5 : 0.005

    const target = focusTargetRef.current
    if (target) {
      controls.target.lerp(target, 0.06)
      // Snap when close enough to avoid endless micro-movement
      if (controls.target.distanceTo(target) < 0.0001) {
        controls.target.copy(target)
        focusTargetRef.current = null
      }
    }
  })

  const handleFocus = useCallback((pos: [number, number, number], radiusAU: number) => {
    focusTargetRef.current = new THREE.Vector3(pos[0], pos[1], pos[2])
    focusedRadiusRef.current = radiusAU
  }, [])

  return (
    <>
      {/* Minimal ambient — space is dark */}
      <ambientLight intensity={0.08} />

      {/* Background star field */}
      <Stars
        radius={200}
        depth={80}
        count={4000}
        factor={5}
        saturation={0.15}
        fade
        speed={0.3}
      />

      {/* Stars */}
      {stellar?.stars?.map((star) => (
        <StarMesh
          key={star.id}
          star={star}
          onSelect={(s) => onSelect({ type: 'star', data: s })}
          onFocus={handleFocus}
          isSelected={selected?.type === 'star' && selected.data.id === star.id}
        />
      ))}

      {/* Orbit lines (real AU) — translated to parent body position */}
      {orbits.map((orbit) => {
        const parentPos = positionMap.get(orbit.parent_id) ?? null
        return (
          <OrbitLine
            key={orbit.body_id}
            orbit={orbit}
            parentPosition={parentPos}
          />
        )
      })}

      {/* All bodies (planets + moons + asteroids) */}
      {allBodies.map((body) => (
        <PlanetMesh
          key={body.id}
          planet={body}
          position={positionMap.get(body.id) ?? [1, 0, 0]}
          labelVisible={labelVisibility[body.id] ?? true}
          satelliteCount={satelliteCountMap.get(body.id) ?? 0}
          onSelect={(p) => onSelect({ type: 'planet', data: p })}
          onFocus={handleFocus}
          isSelected={selected?.type === 'planet' && selected.data.id === body.id}
        />
      ))}

      {/* Habitable zone */}
      {hzData && <HabitableZoneRing data={hzData} />}

      {/* Camera controls — extreme zoom range for real scale */}
      <OrbitControls
        ref={controlsRef}
        makeDefault
        enableDamping
        dampingFactor={0.08}
        minDistance={0.005}
        maxDistance={200}
        maxPolarAngle={Math.PI * 0.9}
        zoomSpeed={1.5}
        onChange={onControlsChange}
      />

      {/* Read camera distance (no visual output, just drives overlay) */}
      <ScaleIndicator />
    </>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function StellarSystemViewer({
  stellar,
  planets,
  habitableZones,
}: StellarSystemViewerProps) {
  const [selected, setSelected] = useState<SelectedBody>(null)
  const controlsRef = useRef<any>(null)
  const focusTargetRef = useRef<THREE.Vector3 | null>(null)
  // Radius (AU) of the body the camera is flying toward; null = no focus.
  // Drives dynamic OrbitControls.minDistance so small bodies remain reachable
  // and large bodies (stars) can't be zoomed into.
  const focusedRadiusRef = useRef<number | null>(null)
  const [cameraDist, setCameraDist] = useState(0)

  // Merge planets + stellar bodies (moons, asteroids) into one list.
  // Deduplicate by id: planets (geological layer) take priority over
  // stellar bodies (astronomy layer) since they carry richer data
  // (atmosphere, hydrosphere, etc.).  Without dedup, worlds that list
  // all bodies in both stellar.yaml and planets.yaml would render
  // duplicate labels at the same position.
  const allBodies = useMemo(() => {
    const planetList = planets ?? []
    const bodyList = stellar?.bodies ?? []
    const planetIds = new Set(planetList.map((p) => p.id))
    const uniqueBodies = bodyList.filter((b) => !planetIds.has(b.id))
    return [...planetList, ...uniqueBodies]
  }, [planets, stellar?.bodies])

  const orbits = stellar?.orbits ?? []
  const orbitMap = useMemo(() => buildOrbitLookup(orbits), [orbits])
  const satelliteCountMap = useMemo(() => buildSatelliteCountMap(orbits), [orbits])
  const positionMap = useMemo(
    () => resolvePositions(stellar?.stars ?? [], allBodies, orbitMap),
    [stellar?.stars, allBodies, orbitMap],
  )
  const initialDist = useMemo(() => computeInitialCameraDistance(orbits), [orbits])

  // Update displayed camera distance on each control change.
  // Use distance from camera to orbit target (what the user is looking at),
  // NOT distance to world origin — otherwise zooming into a planet far from
  // the star gives misleading values that can increase while zooming in.
  const handleControlsChange = useCallback(() => {
    const controls = controlsRef.current
    if (controls) {
      const cam = controls.object as THREE.Camera
      const target = controls.target as THREE.Vector3
      setCameraDist(cam.position.distanceTo(target))
    }
  }, [])

  if (!stellar?.stars?.length) {
    return (
      <div className="glass-panel p-8 text-center text-gray-400">
        无恒星系数据可用于 3D 可视化
      </div>
    )
  }

  // Format camera distance for display
  let distLabel: string
  if (cameraDist > 1) {
    distLabel = `${cameraDist.toFixed(2)} AU`
  } else if (cameraDist > 0.001) {
    distLabel = `${(cameraDist * 1000).toFixed(1)} × 10⁻³ AU`
  } else {
    const km = cameraDist * 149_597_870.7
    if (km > 1_000_000) distLabel = `${(km / 1_000_000).toFixed(1)}M km`
    else distLabel = `${(km).toFixed(0)} km`
  }

  return (
    <div className="relative w-full" style={{ height: '70vh', minHeight: '500px' }}>
      <Suspense
        fallback={
          <div className="flex items-center justify-center h-full text-gray-500">
            加载 3D 场景...
          </div>
        }
      >
        <Canvas
          camera={{
            position: [0, initialDist * 0.4, initialDist],
            fov: 50,
            near: 0.00001,
            far: 5000,
          }}
          gl={{
            logarithmicDepthBuffer: true,
            antialias: true,
            toneMapping: THREE.ACESFilmicToneMapping,
            toneMappingExposure: 1.2,
          }}
          style={{ background: '#030308', borderRadius: '0.75rem' }}
          onPointerMissed={() => {
            setSelected(null)
            focusedRadiusRef.current = null
          }}
        >
          <Scene
            stellar={stellar}
            allBodies={allBodies}
            positionMap={positionMap}
            satelliteCountMap={satelliteCountMap}
            orbitMap={orbitMap}
            habitableZones={habitableZones}
            selected={selected}
            onSelect={setSelected}
            controlsRef={controlsRef}
            onControlsChange={handleControlsChange}
            focusTargetRef={focusTargetRef}
            focusedRadiusRef={focusedRadiusRef}
          />
        </Canvas>
      </Suspense>

      {/* Info panel overlay */}
      <InfoPanel selected={selected} onClose={() => setSelected(null)} />

      {/* HUD overlays */}
      <div className="absolute top-3 left-3 z-10 pointer-events-none space-y-1">
        <div className="text-xs text-gray-500">
          🖱 拖拽旋转 · 滚轮缩放 · 单击选中 · 双击聚焦
        </div>
        <div className="text-xs text-gray-600 font-mono">
          视距: {distLabel}
        </div>
        <div className="flex items-center gap-1 text-xs text-gray-600">
          <span className="inline-block w-3 h-1.5 rounded-sm bg-green-600/30 border border-green-600/20" />
          宜居带
          <span className="ml-2 inline-block w-3 border-t border-dashed border-blue-500/40" />
          雪线
        </div>
        <div className="text-[10px] text-gray-700 mt-1">
          真实比例 · 1 单位 = 1 AU
        </div>
      </div>
    </div>
  )
}
