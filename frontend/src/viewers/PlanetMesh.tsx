/**
 * PlanetMesh — renders a planet with type-based procedural coloring.
 */

import { useRef, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { planetRadiusScale, computeOrbitalPosition } from './utils/scale'

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
  orbit: OrbitalElementsData | null
  onSelect?: (planet: PlanetData) => void
  isSelected?: boolean
}

/**
 * Get a base color for a planet based on its type and properties.
 */
function getPlanetColor(planet: PlanetData): THREE.Color {
  const type = planet.planet_type ?? 'terrestrial'

  switch (type) {
    case 'terrestrial': {
      const water = planet.hydrosphere?.water_coverage ?? 0.3
      // More water = more blue, less = more brown/green
      const r = 0.25 + (1 - water) * 0.35
      const g = 0.3 + water * 0.15
      const b = 0.15 + water * 0.55
      return new THREE.Color(r, g, b)
    }
    case 'gas_giant': {
      // Jupiter-like: orange/brown bands
      return new THREE.Color(0.75, 0.55, 0.3)
    }
    case 'ice_giant': {
      // Uranus/Neptune-like: cyan/blue
      return new THREE.Color(0.3, 0.6, 0.8)
    }
    case 'ocean_world': {
      return new THREE.Color(0.1, 0.25, 0.65)
    }
    case 'dwarf': {
      return new THREE.Color(0.45, 0.4, 0.35)
    }
    default:
      return new THREE.Color(0.5, 0.5, 0.5)
  }
}

export default function PlanetMesh({
  planet,
  orbit,
  onSelect,
  isSelected,
}: PlanetMeshProps) {
  const groupRef = useRef<THREE.Group>(null)
  const planetRef = useRef<THREE.Mesh>(null)

  const visualRadius = planetRadiusScale(planet.radius)
  const color = useMemo(() => getPlanetColor(planet), [planet])
  const axialTilt = ((planet.axial_tilt_deg ?? 0) * Math.PI) / 180

  // Compute position from orbital elements
  const position: [number, number, number] = useMemo(() => {
    if (!orbit) return [5, 0, 0] // fallback if no orbit data
    return computeOrbitalPosition(orbit)
  }, [orbit])

  // Slow rotation animation
  useFrame((_, delta) => {
    if (planetRef.current) {
      const rotationSpeed = planet.rotation_period_days
        ? 0.5 / Math.max(0.1, planet.rotation_period_days)
        : 0.3
      planetRef.current.rotation.y += delta * rotationSpeed
    }
  })

  const hasAtmosphere =
    planet.atmosphere != null &&
    (planet.atmosphere.surface_pressure_atm ?? 0) > 0.01

  return (
    <group ref={groupRef} position={position}>
      {/* Planet body */}
      <mesh
        ref={planetRef}
        rotation={[axialTilt, 0, 0]}
        onClick={(e) => {
          e.stopPropagation()
          onSelect?.(planet)
        }}
        onPointerOver={(e) => {
          e.stopPropagation()
          document.body.style.cursor = 'pointer'
        }}
        onPointerOut={() => {
          document.body.style.cursor = 'default'
        }}
      >
        <sphereGeometry args={[visualRadius, 24, 24]} />
        <meshStandardMaterial
          color={color}
          roughness={0.8}
          metalness={0.1}
        />
      </mesh>

      {/* Atmosphere glow — slightly larger transparent sphere */}
      {hasAtmosphere && (
        <mesh rotation={[axialTilt, 0, 0]} scale={1.15}>
          <sphereGeometry args={[visualRadius, 16, 16]} />
          <meshBasicMaterial
            color={new THREE.Color(0.4, 0.6, 1.0)}
            transparent
            opacity={0.1}
            side={THREE.BackSide}
          />
        </mesh>
      )}

      {/* Selection ring */}
      {isSelected && (
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <ringGeometry args={[visualRadius * 1.4, visualRadius * 1.6, 32]} />
          <meshBasicMaterial
            color="#00d4ff"
            transparent
            opacity={0.6}
            side={THREE.DoubleSide}
          />
        </mesh>
      )}

      {/* Label */}
      <Html
        position={[0, visualRadius + 0.4, 0]}
        center
        style={{ pointerEvents: 'none' }}
      >
        <div
          style={{
            color: '#e0e0e0',
            fontSize: '11px',
            fontWeight: 500,
            textShadow: '0 0 6px rgba(0,0,0,0.8)',
            whiteSpace: 'nowrap',
            userSelect: 'none',
          }}
        >
          {planet.name}
        </div>
      </Html>
    </group>
  )
}

export type { PlanetData, OrbitalElementsData }
