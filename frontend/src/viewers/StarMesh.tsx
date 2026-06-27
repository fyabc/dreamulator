/**
 * StarMesh — renders a single star as a glowing sphere with black-body color.
 */

import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import * as THREE from 'three'
import { temperatureToColor, luminosityToGlowIntensity } from './utils/starColor'
import { starRadiusScale, distanceScale } from './utils/scale'

interface StarData {
  id: string
  name: string
  temperature?: number | null
  radius?: number | null
  luminosity?: number | null
  spectral_class?: string
  luminosity_class?: string
  mass?: number | null
  position?: { x: number; y: number; z: number }
  derived?: {
    computed_temperature?: number
    computed_radius?: number
    computed_luminosity?: number
  }
}

interface StarMeshProps {
  star: StarData
  onSelect?: (star: StarData) => void
  isSelected?: boolean
}

export default function StarMesh({ star, onSelect, isSelected }: StarMeshProps) {
  const meshRef = useRef<THREE.Mesh>(null)
  const glowRef = useRef<THREE.Mesh>(null)

  // Resolve temperature and radius from input or derived
  const temperature = star.derived?.computed_temperature ?? star.temperature ?? 5772
  const radius = star.derived?.computed_radius ?? star.radius ?? 1.0
  const luminosity = star.derived?.computed_luminosity ?? star.luminosity ?? 1.0

  const color = temperatureToColor(temperature)
  const visualRadius = starRadiusScale(radius)
  const glowIntensity = luminosityToGlowIntensity(luminosity)

  // Star position in scene units
  const pos: [number, number, number] = star.position
    ? [
        distanceScale(star.position.x) || 0,
        distanceScale(star.position.y) || 0,
        distanceScale(star.position.z) || 0,
      ]
    : [0, 0, 0]

  // Gentle rotation animation for the glow shell
  useFrame((_, delta) => {
    if (glowRef.current) {
      glowRef.current.rotation.y += delta * 0.1
    }
  })

  return (
    <group position={pos}>
      {/* Point light from the star */}
      <pointLight
        color={color}
        intensity={Math.min(5, glowIntensity * 2)}
        distance={50}
        decay={1.5}
      />

      {/* Core star sphere */}
      <mesh
        ref={meshRef}
        onClick={(e) => {
          e.stopPropagation()
          onSelect?.(star)
        }}
        onPointerOver={(e) => {
          e.stopPropagation()
          document.body.style.cursor = 'pointer'
        }}
        onPointerOut={() => {
          document.body.style.cursor = 'default'
        }}
      >
        <sphereGeometry args={[visualRadius, 32, 32]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={glowIntensity}
          roughness={1}
          metalness={0}
        />
      </mesh>

      {/* Glow shell — slightly larger, semi-transparent */}
      <mesh ref={glowRef} scale={1.3}>
        <sphereGeometry args={[visualRadius, 16, 16]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.15}
          side={THREE.BackSide}
        />
      </mesh>

      {/* Selection indicator */}
      {isSelected && (
        <mesh scale={1.6}>
          <ringGeometry args={[visualRadius * 0.9, visualRadius * 1.1, 32]} />
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
        position={[0, visualRadius + 0.5, 0]}
        center
        style={{ pointerEvents: 'none' }}
      >
        <div
          style={{
            color: '#00d4ff',
            fontSize: '12px',
            fontWeight: 600,
            textShadow: '0 0 8px rgba(0,212,255,0.8)',
            whiteSpace: 'nowrap',
            userSelect: 'none',
          }}
        >
          {star.name}
        </div>
      </Html>
    </group>
  )
}

export type { StarData }
