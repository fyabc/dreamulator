/**
 * StellarSystemViewer — main 3D visualization container.
 *
 * Renders an interactive Three.js scene at **real astronomical proportions**:
 * - All distances in AU (1 scene unit = 1 AU)
 * - Star and planet radii at true scale
 * - Camera frames the system, an orbit with its primary, or a single body
 *
 * Visibility of sub-pixel bodies is handled by Label components
 * (dot + leader line), not by distorting proportions.
 *
 * Uses logarithmicDepthBuffer to handle the enormous near/far ratio
 * (camera at 10 AU viewing objects at 0.00004 AU radius).
 */

import { useState, useMemo, Suspense, useRef, useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Stars } from '@react-three/drei'
import * as THREE from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import StarMesh from './StarMesh'
import PlanetMesh from './PlanetMesh'
import OrbitLine from './OrbitLine'
import HabitableZoneRing from './HabitableZoneRing'
import InfoPanel from './InfoPanel'
import ErrorBoundary from '../components/ErrorBoundary'
import { computeOrbitalPosition, earthRadiiToAU, solarRadiiToAU } from './utils/scale'
import {
  orbitFrameDirection, orbitFrameNormal, orbitFrameRadius, stellarCloseUpDistance, stellarFrameDistance, stellarNearPlane,
  STELLAR_DEFAULT_NEAR_AU, STELLAR_MAX_POLAR_ANGLE, type StellarFocusMode,
} from './utils/stellarCamera'
import type { StarData } from './StarMesh'
import type { PlanetData, OrbitalElementsData } from './PlanetMesh'
import type { SelectedBody } from './InfoPanel'
import type { CatalogBody, CatalogStar } from '../api/catalogAdapter'
import type { CVTMesh } from './map/types'

type Vec3 = [number, number, number]

interface CameraFlight {
  target: THREE.Vector3
  frameRadius?: number
  orbitNormal?: THREE.Vector3
  elapsed: number
  start?: { target: THREE.Vector3; direction: THREE.Vector3; distance: number }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StellarSystemData {
  name?: string
  stars?: StarData[]
  orbits?: OrbitalElementsData[]
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
  /** Planet ID → terrain texture (equirectangular).  Populated by the page. */
  planetTextures?: Map<string, THREE.Texture>
  focusBodyId?: string
  focusRequest?: { id: string; mode: StellarFocusMode; nonce: number } | null
  detailsOpen: boolean
  onCloseDetails: () => void
  /** CVT mesh for the currently selected planet — enables terrain summary in InfoPanel. */
  selectedPlanetCvtMesh?: CVTMesh | null
  /** System-catalog entries by body id — enriches the InfoPanel (orbit/derived fields). */
  bodyCatalog?: Map<string, CatalogBody>
  /** System-catalog entries by star id — enriches the InfoPanel (age/HZ fields). */
  starCatalog?: Map<string, CatalogStar>
  /** Called when the user selects or deselects a body. */
  onSelectionChange?: (body: SelectedBody) => void
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

function formatCameraDistance(distance: number) {
  if (distance > 1) return `${distance.toFixed(2)} AU`
  if (distance > 0.001) return `${(distance * 1000).toFixed(1)} × 10⁻³ AU`
  return `${(distance * 149_597_870.7).toFixed(0)} km`
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
  planetTextures,
  selected,
  selectedRadius,
  onSelect,
  controlsRef,
  onViewDistance,
  flightRef,
  pivotRadiusRef,
}: {
  stellar: StellarSystemData | null | undefined
  allBodies: PlanetData[]
  positionMap: Map<string, Vec3>
  satelliteCountMap: Map<string, number>
  orbitMap: Map<string, OrbitalElementsData>
  habitableZones: HabitableZoneData | null | undefined
  planetTextures?: Map<string, THREE.Texture>
  selected: SelectedBody
  selectedRadius: number
  onSelect: (body: SelectedBody) => void
  controlsRef: React.MutableRefObject<OrbitControlsImpl | null>
  onViewDistance: (distance: number) => void
  flightRef: React.MutableRefObject<CameraFlight | null>
  pivotRadiusRef: React.MutableRefObject<number | null>
}) {
  const orbits = stellar?.orbits ?? []
  const hzData = useMemo(() => resolveHZ(habitableZones), [habitableZones])
  const selectedId = selected?.data.id
  const selectedPosition = useMemo(() => {
    const position = selectedId && positionMap.get(selectedId)
    return position ? new THREE.Vector3(...position) : null
  }, [positionMap, selectedId])
  const [orbitHidden, setOrbitHidden] = useState(false)

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

  useFrame(({ camera }, delta) => {
    const controls = controlsRef.current
    if (!controls || !(camera instanceof THREE.PerspectiveCamera)) return

    const pivotRadius = pivotRadiusRef.current
    controls.minDistance = pivotRadius == null ? 0.005 : pivotRadius * 1.5
    const flight = flightRef.current
    if (flight) {
      const start = flight.start ??= {
        target: controls.target.clone(),
        direction: camera.position.clone().sub(controls.target).normalize(),
        distance: Math.max(camera.position.distanceTo(controls.target), controls.minDistance),
      }
      const frameDistance = flight.frameRadius == null ? start.distance
        : flight.orbitNormal ? stellarFrameDistance(flight.frameRadius, camera.fov, camera.aspect)
        : stellarCloseUpDistance(flight.frameRadius, camera.fov, camera.aspect)
      const destinationDirection = flight.orbitNormal ? orbitFrameDirection(start.direction, flight.orbitNormal) : start.direction
      flight.elapsed += delta
      const progress = THREE.MathUtils.smoothstep(flight.elapsed, 0, 0.9)
      const distance = Math.exp(THREE.MathUtils.lerp(Math.log(start.distance), Math.log(frameDistance), progress))
      const direction = start.direction.clone().lerp(destinationDirection, progress).normalize()
      controls.target.lerpVectors(start.target, flight.target, progress)
      camera.position.copy(controls.target).addScaledVector(direction, distance)
      camera.lookAt(controls.target)
      if (progress === 1) flightRef.current = null
    }

    const distance = camera.position.distanceTo(controls.target)
    const near = stellarNearPlane(distance)
    if (Math.abs(near - camera.near) > camera.near * 0.1) {
      camera.near = near
      camera.updateProjectionMatrix()
    }
    const hideOrbit = selectedPosition != null && selectedRadius > 0 &&
      camera.position.distanceTo(selectedPosition) <= stellarCloseUpDistance(selectedRadius, camera.fov, camera.aspect) * 1.1
    if (orbitHidden !== hideOrbit) setOrbitHidden(hideOrbit)
    onViewDistance(distance)
  })

  const handleFocus = useCallback((pos: [number, number, number], radiusAU: number) => {
    flightRef.current = { target: new THREE.Vector3(...pos), elapsed: 0 }
    pivotRadiusRef.current = radiusAU > 0 ? radiusAU : null
  }, [flightRef, pivotRadiusRef])

  const stopFlight = useCallback(() => { flightRef.current = null }, [flightRef])

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
        const highlighted = selectedId === orbit.body_id
        if (highlighted && orbitHidden) return null
        const parentPos = positionMap.get(orbit.parent_id) ?? null
        return (
          <OrbitLine
            key={orbit.body_id}
            orbit={orbit}
            parentPosition={parentPos}
            highlighted={highlighted}
          />
        )
      })}

      {/* All bodies (planets + moons + asteroids) */}
      {allBodies.map((body) => (
        <PlanetMesh
          key={body.id}
          planet={body}
          position={positionMap.get(body.id) ?? [1, 0, 0]}
          terrainTexture={planetTextures?.get(body.id)}
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
        maxPolarAngle={STELLAR_MAX_POLAR_ANGLE}
        zoomSpeed={1.5}
        onStart={stopFlight}
      />
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
  planetTextures,
  focusBodyId,
  focusRequest,
  detailsOpen,
  onCloseDetails,
  selectedPlanetCvtMesh,
  bodyCatalog,
  starCatalog,
  onSelectionChange,
}: StellarSystemViewerProps) {
  const { t } = useTranslation('map')
  const controlsRef = useRef<OrbitControlsImpl | null>(null)
  const flightRef = useRef<CameraFlight | null>(null)
  const pivotRadiusRef = useRef<number | null>(null)
  const [cameraDistanceLabel, setCameraDistanceLabel] = useState('')
  const lastDistanceLabel = useRef('')

  // The page passes the catalog's merged body list (stellar.yaml +
  // planets.yaml joined server-side, planets.yaml taking priority for shared
  // fields) — no client-side merging/dedup needed anymore.
  const allBodies = useMemo(() => planets ?? [], [planets])
  const selectedPlanet = allBodies.find((body) => body.id === focusBodyId)
  const selectedStar = stellar?.stars?.find((star) => star.id === focusBodyId)
  const selected: SelectedBody = selectedPlanet ? { type: 'planet', data: selectedPlanet }
    : selectedStar ? { type: 'star', data: selectedStar } : null

  const orbits = stellar?.orbits ?? []
  const orbitMap = useMemo(() => buildOrbitLookup(orbits), [orbits])
  const satelliteCountMap = useMemo(() => buildSatelliteCountMap(orbits), [orbits])
  const positionMap = useMemo(
    () => resolvePositions(stellar?.stars ?? [], allBodies, orbitMap),
    [stellar?.stars, allBodies, orbitMap],
  )
  const initialDist = useMemo(() => computeInitialCameraDistance(orbits), [orbits])

  const handleViewDistance = useCallback((distance: number) => {
    const label = formatCameraDistance(distance)
    if (label !== lastDistanceLabel.current) {
      lastDistanceLabel.current = label
      setCameraDistanceLabel(label)
    }
  }, [])

  const bodyRadiusAU = useCallback((id: string) => {
    const body = allBodies.find((candidate) => candidate.id === id)
    if (body) return earthRadiiToAU(body.radius)
    const star = stellar?.stars?.find((candidate) => candidate.id === id)
    return star ? solarRadiiToAU(star.derived?.computed_radius ?? star.radius ?? 0) : 0
  }, [allBodies, stellar?.stars])

  const focusBody = useCallback((id: string, mode?: StellarFocusMode) => {
    const position = positionMap.get(id)
    if (!position) return
    const radius = bodyRadiusAU(id)
    if (mode === 'orbit') {
      const orbit = orbitMap.get(id)
      if (!orbit || orbit.semi_major_axis_au <= 0) return
      const parentRadius = bodyRadiusAU(orbit.parent_id)
      const parentPosition = positionMap.get(orbit.parent_id) ?? [0, 0, 0]
      pivotRadiusRef.current = parentRadius > 0 ? parentRadius : Number.EPSILON
      flightRef.current = {
        target: new THREE.Vector3(...parentPosition),
        frameRadius: orbitFrameRadius(orbit, radius, parentRadius),
        orbitNormal: orbitFrameNormal(orbit),
        elapsed: 0,
      }
      return
    }
    pivotRadiusRef.current = radius > 0 ? radius : null
    flightRef.current = {
      target: new THREE.Vector3(...position),
      frameRadius: mode === 'close-up' && radius > 0 ? radius : undefined,
      elapsed: 0,
    }
  }, [positionMap, orbitMap, bodyRadiusAU])

  useEffect(() => {
    if (focusBodyId) focusBody(focusBodyId)
    else {
      flightRef.current = null
      pivotRadiusRef.current = null
    }
  }, [focusBodyId, focusBody])

  const lastFocusNonceRef = useRef(0)
  useEffect(() => {
    if (!focusRequest || focusRequest.id !== focusBodyId || focusRequest.nonce === lastFocusNonceRef.current) return
    lastFocusNonceRef.current = focusRequest.nonce
    focusBody(focusRequest.id, focusRequest.mode)
  }, [focusRequest, focusBody, focusBodyId])

  // InfoPanel enrichment: catalog entries + orbit-derived context
  const selectedCatalogBody =
    selected?.type === 'planet' ? bodyCatalog?.get(selected.data.id) : undefined
  const selectedCatalogStar =
    selected?.type === 'star' ? starCatalog?.get(selected.data.id) : undefined
  const selectedOrbit = selected ? orbitMap.get(selected.data.id) : undefined
  const selectedParentName = selectedOrbit
    ? bodyCatalog?.get(selectedOrbit.parent_id)?.name ??
      starCatalog?.get(selectedOrbit.parent_id)?.name
    : undefined
  const selectedSatelliteCount = selected
    ? satelliteCountMap.get(selected.data.id) ?? 0
    : 0

  if (!stellar?.stars?.length) {
    return (
      <div className="glass-panel p-8 text-center text-gray-400">
        {t('viewer.noData')}
      </div>
    )
  }

  const distLabel = cameraDistanceLabel || formatCameraDistance(Math.hypot(initialDist, initialDist * 0.4))
  const showLegend = !!resolveHZ(habitableZones)

  return (
    <div className="absolute inset-0 flex flex-col">
      <div className="relative min-h-0 flex-1 bg-[#030308]">
        <ErrorBoundary message={t('viewer.renderError')}>
          <Suspense
            fallback={
              <div className="flex items-center justify-center h-full text-gray-300">
                {t('viewer.loading')}
              </div>
            }
          >
            <Canvas
              className="isolate"
              camera={{
                position: [0, initialDist * 0.4, initialDist],
                fov: 50,
                near: STELLAR_DEFAULT_NEAR_AU,
                far: 5000,
              }}
              gl={{
                logarithmicDepthBuffer: true,
                antialias: true,
                toneMapping: THREE.ACESFilmicToneMapping,
                toneMappingExposure: 1.2,
              }}
              onPointerMissed={() => onSelectionChange?.(null)}
            >
              <Scene
                stellar={stellar}
                allBodies={allBodies}
                positionMap={positionMap}
                satelliteCountMap={satelliteCountMap}
                orbitMap={orbitMap}
                habitableZones={habitableZones}
                planetTextures={planetTextures}
                selected={selected}
                selectedRadius={focusBodyId ? bodyRadiusAU(focusBodyId) : 0}
                onSelect={(body) => onSelectionChange?.(body)}
                controlsRef={controlsRef}
                onViewDistance={handleViewDistance}
                flightRef={flightRef}
                pivotRadiusRef={pivotRadiusRef}
              />
            </Canvas>
          </Suspense>
        </ErrorBoundary>
        {detailsOpen && <InfoPanel
          key={selected?.data.id}
          selected={selected}
          onClose={onCloseDetails}
          cvtMesh={selectedPlanetCvtMesh}
          catalogBody={selectedCatalogBody}
          catalogStar={selectedCatalogStar}
          parentName={selectedParentName}
          satelliteCount={selectedSatelliteCount}
        />}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-space-border bg-space-bg px-3 py-2 text-xs text-gray-300 sm:px-5">
        <span className="font-semibold text-gray-100">{t('viewer.scaleHint')}</span>
        <span className="tabular-nums">{t('viewer.distance')} {distLabel}</span>
        {showLegend && <ul className="flex flex-wrap items-center gap-x-3 gap-y-1 sm:ml-auto">
          <li className="flex items-center gap-1.5"><span className="h-1.5 w-3 rounded-sm bg-green-500/60" />{t('viewer.habitableZone')}</li>
          <li className="flex items-center gap-1.5"><span className="w-3 border-t border-dashed border-green-400" />{t('viewer.habitableZoneOptimistic')}</li>
          <li className="flex items-center gap-1.5"><span className="w-3 border-t border-dashed border-blue-400" />{t('viewer.snowLine')}</li>
        </ul>}
      </div>
    </div>
  )
}
