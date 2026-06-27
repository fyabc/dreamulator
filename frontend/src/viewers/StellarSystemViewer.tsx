/**
 * StellarSystemViewer — main 3D visualization container.
 *
 * Renders an interactive Three.js scene with stars, planets,
 * orbital paths, and habitable zone indicators, all driven by
 * actual world data.
 */

import { useState, useMemo, Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Stars } from '@react-three/drei'
import StarMesh from './StarMesh'
import PlanetMesh from './PlanetMesh'
import OrbitLine from './OrbitLine'
import HabitableZoneRing from './HabitableZoneRing'
import InfoPanel from './InfoPanel'
import type { StarData } from './StarMesh'
import type { PlanetData, OrbitalElementsData } from './PlanetMesh'
import type { SelectedBody } from './InfoPanel'

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

/**
 * Build a lookup from orbit body_id to orbital elements.
 */
function buildOrbitLookup(
  orbits: OrbitalElementsData[],
): Map<string, OrbitalElementsData> {
  const map = new Map<string, OrbitalElementsData>()
  for (const orbit of orbits) {
    map.set(orbit.body_id, orbit)
  }
  return map
}

/**
 * Find the habitable zone data for the primary star.
 * The habitable zones export is keyed by star (array of star entries).
 */
function resolveHZ(
  habitableZones: HabitableZoneData | null | undefined,
): HabitableZoneData | null {
  if (!habitableZones) return null
  // The export format is { stars: [{ id, habitable_zone, ... }] }
  // or a flat object with habitable_zone key
  if (habitableZones.habitable_zone) return habitableZones

  // Check if it's an array-based format
  const stars = (habitableZones as Record<string, unknown>).stars
  if (Array.isArray(stars) && stars.length > 0) {
    return stars[0] as HabitableZoneData
  }

  return null
}

/**
 * The inner scene rendered inside the Canvas.
 */
function Scene({
  stellar,
  planets,
  habitableZones,
  selected,
  onSelect,
}: {
  stellar: StellarSystemData | null | undefined
  planets: PlanetData[] | null | undefined
  habitableZones: HabitableZoneData | null | undefined
  selected: SelectedBody
  onSelect: (body: SelectedBody) => void
}) {
  const orbits = stellar?.orbits ?? []
  const orbitMap = useMemo(() => buildOrbitLookup(orbits), [orbits])
  const hzData = useMemo(() => resolveHZ(habitableZones), [habitableZones])

  return (
    <>
      {/* Lighting */}
      <ambientLight intensity={0.15} />

      {/* Background stars */}
      <Stars
        radius={100}
        depth={60}
        count={3000}
        factor={4}
        saturation={0.2}
        fade
        speed={0.5}
      />

      {/* Stars */}
      {stellar?.stars?.map((star) => (
        <StarMesh
          key={star.id}
          star={star}
          onSelect={(s) => onSelect({ type: 'star', data: s })}
          isSelected={selected?.type === 'star' && selected.data.id === star.id}
        />
      ))}

      {/* Orbit lines */}
      {orbits.map((orbit) => (
        <OrbitLine
          key={orbit.body_id}
          orbit={orbit}
          color="#3a3a7a"
          opacity={0.4}
        />
      ))}

      {/* Planets */}
      {planets?.map((planet) => (
        <PlanetMesh
          key={planet.id}
          planet={planet}
          orbit={orbitMap.get(planet.id) ?? null}
          onSelect={(p) => onSelect({ type: 'planet', data: p })}
          isSelected={selected?.type === 'planet' && selected.data.id === planet.id}
        />
      ))}

      {/* Habitable zone */}
      {hzData && <HabitableZoneRing data={hzData} />}

      {/* Camera controls */}
      <OrbitControls
        makeDefault
        enableDamping
        dampingFactor={0.08}
        minDistance={2}
        maxDistance={80}
        maxPolarAngle={Math.PI * 0.85}
      />
    </>
  )
}

/**
 * Fallback UI while the 3D scene loads.
 */
function LoadingFallback() {
  return (
    <div className="flex items-center justify-center h-full text-gray-500">
      加载 3D 场景...
    </div>
  )
}

export default function StellarSystemViewer({
  stellar,
  planets,
  habitableZones,
}: StellarSystemViewerProps) {
  const [selected, setSelected] = useState<SelectedBody>(null)

  const handleDeselect = () => setSelected(null)

  // No data state
  if (!stellar?.stars?.length) {
    return (
      <div className="glass-panel p-8 text-center text-gray-400">
        无恒星系数据可用于 3D 可视化
      </div>
    )
  }

  return (
    <div className="relative w-full" style={{ height: '70vh', minHeight: '500px' }}>
      <Suspense fallback={<LoadingFallback />}>
        <Canvas
          camera={{ position: [0, 8, 16], fov: 50, near: 0.1, far: 200 }}
          style={{ background: '#050510', borderRadius: '0.75rem' }}
          onClick={(e) => {
            // Click on empty space to deselect
            if (e.target === e.currentTarget) {
              handleDeselect()
            }
          }}
        >
          <Scene
            stellar={stellar}
            planets={planets}
            habitableZones={habitableZones}
            selected={selected}
            onSelect={setSelected}
          />
        </Canvas>
      </Suspense>

      {/* Info panel overlay */}
      <InfoPanel selected={selected} onClose={handleDeselect} />

      {/* Legend */}
      <div className="absolute top-3 left-3 z-10 pointer-events-none">
        <div className="flex flex-col gap-1 text-xs text-gray-500">
          <span>🖱 拖拽旋转 · 滚轮缩放</span>
          <span>点击天体查看详情</span>
          {habitableZones && (
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-1.5 rounded-sm bg-green-600/40" />
              宜居带
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
