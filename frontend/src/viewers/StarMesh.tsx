/**
 * StarMesh — renders a star at real astronomical proportions.
 *
 * The sphere geometry uses the actual stellar radius converted to AU
 * (e.g. Sol ≈ 0.00465 AU). At system-view distances this is sub-pixel,
 * which is physically correct — Space Engine behaves the same way.
 *
 * Visibility is handled by:
 * 1. A glow shell at MIN_VISUAL_RADIUS (always seeable/clickable).
 * 2. A PointLight that illuminates nearby planets at any zoom.
 * 3. The Label component (dot + leader line + name) via <Html>.
 */

import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { temperatureToColor, luminosityToGlowIntensity } from './utils/starColor'
import {
  solarRadiiToAU,
  effectiveVisualRadius,
} from './utils/scale'
import Label from './Label'

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
  /** Double-click: fly camera to this body */
  onFocus?: (position: [number, number, number]) => void
  isSelected?: boolean
}

export default function StarMesh({ star, onSelect, onFocus, isSelected }: StarMeshProps) {
  const glowRef = useRef<THREE.Mesh>(null)

  // Resolve from input or derived
  const temperature = star.derived?.computed_temperature ?? star.temperature ?? 5772
  const radiusSun = star.derived?.computed_radius ?? star.radius ?? 1.0
  const luminosity = star.derived?.computed_luminosity ?? star.luminosity ?? 1.0

  const color = temperatureToColor(temperature)
  const realRadiusAU = solarRadiiToAU(radiusSun)
  const visualRadiusAU = effectiveVisualRadius(realRadiusAU)
  const glowIntensity = luminosityToGlowIntensity(luminosity)

  // Position in AU
  const pos: [number, number, number] = star.position
    ? [star.position.x, star.position.y, star.position.z]
    : [0, 0, 0]

  // Subtle rotation for the glow shell
  useFrame((_, delta) => {
    if (glowRef.current) {
      glowRef.current.rotation.y += delta * 0.05
    }
  })

  const typeLabel = `${star.spectral_class ?? ''}${star.luminosity_class ?? ''} · ${Math.round(temperature)} K`

  return (
    <group position={pos}>
      {/* Point light — illuminates planets regardless of zoom */}
      <pointLight
        color={color}
        intensity={Math.min(8, glowIntensity * 3)}
        distance={100}
        decay={1.5}
      />

      {/* Real-scale star sphere */}
      <mesh
        onClick={(e) => {
          e.stopPropagation()
          onSelect?.(star)
        }}
        onDoubleClick={(e) => {
          e.stopPropagation()
          onFocus?.(pos)
        }}
        onPointerOver={(e) => {
          e.stopPropagation()
          document.body.style.cursor = 'pointer'
        }}
        onPointerOut={() => {
          document.body.style.cursor = 'default'
        }}
      >
        <sphereGeometry args={[realRadiusAU, 32, 32]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={glowIntensity * 1.5}
          roughness={1}
          metalness={0}
        />
      </mesh>

      {/* Minimum-size glow shell — ensures star is visible at system scale.
          Uses additive blending for a soft corona look. */}
      <mesh ref={glowRef}>
        <sphereGeometry args={[visualRadiusAU, 16, 16]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.25}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </mesh>

      {/* Outer soft glow */}
      <mesh>
        <sphereGeometry args={[visualRadiusAU * 2.5, 12, 12]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.06}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          side={THREE.BackSide}
        />
      </mesh>

      {/* Label with leader line */}
      <Label
        name={star.name}
        color={`#${color.getHexString()}`}
        glowColor={`#${color.getHexString()}`}
        subtitle={typeLabel}
        selected={isSelected}
        onClick={() => onSelect?.(star)}
        onDoubleClick={() => onFocus?.(pos)}
      />
    </group>
  )
}

export type { StarData }
