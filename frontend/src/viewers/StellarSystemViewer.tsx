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
import type { StarData } from './StarMesh'
import type { PlanetData, OrbitalElementsData } from './PlanetMesh'
import type { SelectedBody } from './InfoPanel'

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
  planets,
  habitableZones,
  selected,
  onSelect,
  controlsRef,
  onControlsChange,
  focusTargetRef,
}: {
  stellar: StellarSystemData | null | undefined
  planets: PlanetData[] | null | undefined
  habitableZones: HabitableZoneData | null | undefined
  selected: SelectedBody
  onSelect: (body: SelectedBody) => void
  controlsRef: React.MutableRefObject<any>
  onControlsChange: () => void
  focusTargetRef: React.MutableRefObject<THREE.Vector3 | null>
}) {
  const orbits = stellar?.orbits ?? []
  const orbitMap = useMemo(() => buildOrbitLookup(orbits), [orbits])
  const hzData = useMemo(() => resolveHZ(habitableZones), [habitableZones])

  // Smoothly fly camera target to focused body each frame
  useFrame(() => {
    const controls = controlsRef.current
    const target = focusTargetRef.current
    if (controls && target) {
      controls.target.lerp(target, 0.06)
      // Snap when close enough to avoid endless micro-movement
      if (controls.target.distanceTo(target) < 0.0001) {
        controls.target.copy(target)
        focusTargetRef.current = null
      }
    }
  })

  const handleFocus = useCallback((pos: [number, number, number]) => {
    focusTargetRef.current = new THREE.Vector3(pos[0], pos[1], pos[2])
  }, [focusTargetRef])

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

      {/* Orbit lines (real AU) */}
      {orbits.map((orbit) => (
        <OrbitLine key={orbit.body_id} orbit={orbit} />
      ))}

      {/* Planets */}
      {planets?.map((planet) => (
        <PlanetMesh
          key={planet.id}
          planet={planet}
          orbit={orbitMap.get(planet.id) ?? null}
          onSelect={(p) => onSelect({ type: 'planet', data: p })}
          onFocus={handleFocus}
          isSelected={selected?.type === 'planet' && selected.data.id === planet.id}
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
        minDistance={0.001}
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
  const [cameraDist, setCameraDist] = useState(0)

  const orbits = stellar?.orbits ?? []
  const initialDist = useMemo(() => computeInitialCameraDistance(orbits), [orbits])

  // Update displayed camera distance on each control change
  const handleControlsChange = useCallback(() => {
    if (controlsRef.current) {
      const cam = controlsRef.current.object as THREE.Camera
      setCameraDist(cam.position.length())
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
          onPointerMissed={() => setSelected(null)}
        >
          <Scene
            stellar={stellar}
            planets={planets}
            habitableZones={habitableZones}
            selected={selected}
            onSelect={setSelected}
            controlsRef={controlsRef}
            onControlsChange={handleControlsChange}
            focusTargetRef={focusTargetRef}
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
