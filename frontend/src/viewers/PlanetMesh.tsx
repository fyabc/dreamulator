/**
 * PlanetMesh — renders a planet at real astronomical proportions.
 *
 * The sphere geometry uses the actual planetary radius in AU
 * (e.g. Earth ≈ 0.0000426 AU — truly tiny at system scale).
 *
 * The Label component (dot + leader line) marks the body's position
 * and keeps it findable at any zoom level.
 */

import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { earthRadiiToAU, formatRadius, formatMass } from './utils/scale'
import Label from './Label'

interface PlanetData {
  id: string
  name: string
  orbits: string
  planet_type?: string
  mass: number
  radius: number
  albedo?: number
  axial_tilt_deg?: number
  rotation_period_days?: number
  atmosphere?: {
    surface_pressure_atm?: number
    composition?: Record<string, number>
  } | null
  hydrosphere?: {
    water_coverage?: number
  } | null
}

interface OrbitalElementsData {
  body_id: string
  parent_id: string
  semi_major_axis_au: number
  eccentricity: number
  inclination_deg: number
  longitude_ascending_node_deg?: number
  argument_of_periapsis_deg?: number
  mean_anomaly_epoch_deg?: number
}

interface PlanetMeshProps {
  planet: PlanetData
  /** Pre-computed absolute position in AU (resolved hierarchically) */
  position: [number, number, number]
  /** Whether the label should be visible (controlled by parent declutter) */
  labelVisible?: boolean
  /** Number of satellites orbiting this body (shown in subtitle) */
  satelliteCount?: number
  onSelect?: (planet: PlanetData) => void
  /** Double-click: fly camera to this body */
  onFocus?: (position: [number, number, number]) => void
  isSelected?: boolean
}

const PLANET_TYPE_LABELS: Record<string, string> = {
  terrestrial: '类地',
  gas_giant: '气态巨行星',
  ice_giant: '冰巨行星',
  ocean_world: '海洋',
  dwarf: '矮行星',
}

/**
 * Procedural color by planet type.
 */
function getPlanetColor(planet: PlanetData): THREE.Color {
  switch (planet.planet_type ?? 'terrestrial') {
    case 'terrestrial': {
      const water = planet.hydrosphere?.water_coverage ?? 0.3
      return new THREE.Color(0.25 + (1 - water) * 0.35, 0.3 + water * 0.15, 0.15 + water * 0.55)
    }
    case 'gas_giant':
      return new THREE.Color(0.75, 0.55, 0.3)
    case 'ice_giant':
      return new THREE.Color(0.3, 0.6, 0.8)
    case 'ocean_world':
      return new THREE.Color(0.1, 0.25, 0.65)
    case 'dwarf':
      return new THREE.Color(0.45, 0.4, 0.35)
    default:
      return new THREE.Color(0.5, 0.5, 0.5)
  }
}

export default function PlanetMesh({
  planet,
  position,
  labelVisible = true,
  satelliteCount = 0,
  onSelect,
  onFocus,
  isSelected,
}: PlanetMeshProps) {
  const planetRef = useRef<THREE.Mesh>(null)

  const realRadiusAU = earthRadiiToAU(planet.radius)
  const color = useMemo(() => getPlanetColor(planet), [planet])
  const axialTilt = ((planet.axial_tilt_deg ?? 0) * Math.PI) / 180

  // Slow self-rotation
  useFrame((_, delta) => {
    if (planetRef.current) {
      const speed = planet.rotation_period_days
        ? 0.3 / Math.max(0.1, planet.rotation_period_days)
        : 0.2
      planetRef.current.rotation.y += delta * speed
    }
  })

  const hasAtmosphere =
    planet.atmosphere != null &&
    (planet.atmosphere.surface_pressure_atm ?? 0) > 0.01

  const typeLabel = PLANET_TYPE_LABELS[planet.planet_type ?? ''] ?? planet.planet_type ?? ''
  const satLabel = satelliteCount > 0 ? ` · ${satelliteCount} satellite${satelliteCount > 1 ? 's' : ''}` : ''
  const subtitle = `${typeLabel} · ${formatRadius(planet.radius)} · ${formatMass(planet.mass)}${satLabel}`

  return (
    <group position={position}>
      {/* Real-scale planet body */}
      <mesh
        ref={planetRef}
        rotation={[axialTilt, 0, 0]}
        onClick={(e) => {
          e.stopPropagation()
          onSelect?.(planet)
        }}
        onDoubleClick={(e) => {
          e.stopPropagation()
          onFocus?.(position)
        }}
        onPointerOver={(e) => {
          e.stopPropagation()
          document.body.style.cursor = 'pointer'
        }}
        onPointerOut={() => {
          document.body.style.cursor = 'default'
        }}
      >
        <sphereGeometry args={[realRadiusAU, 24, 24]} />
        <meshStandardMaterial color={color} roughness={0.8} metalness={0.1} />
      </mesh>

      {/* Atmosphere shell */}
      {hasAtmosphere && (
        <mesh rotation={[axialTilt, 0, 0]} scale={1.08}>
          <sphereGeometry args={[realRadiusAU, 16, 16]} />
          <meshBasicMaterial
            color={new THREE.Color(0.4, 0.6, 1.0)}
            transparent
            opacity={0.1}
            side={THREE.BackSide}
            depthWrite={false}
          />
        </mesh>
      )}

      {/* Label with leader line */}
      <Label
        name={planet.name}
        color={`#${color.getHexString()}`}
        subtitle={subtitle}
        selected={isSelected}
        visible={labelVisible}
        onClick={() => onSelect?.(planet)}
        onDoubleClick={() => onFocus?.(position)}
      />
    </group>
  )
}

export type { PlanetData, OrbitalElementsData }
