/**
 * HabitableZoneRing — renders a translucent ring showing the habitable zone
 * and optional condensation line markers.
 */

import { useMemo } from 'react'
import * as THREE from 'three'
import { Line } from '@react-three/drei'
import { distanceScale } from './utils/scale'

interface HabitableZoneData {
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

interface HabitableZoneRingProps {
  data: HabitableZoneData
  /** Y offset to avoid z-fighting with orbit lines */
  yOffset?: number
}

/**
 * Create a flat ring geometry between inner and outer radii.
 */
function FlatRing({
  innerRadius,
  outerRadius,
  color,
  opacity,
  yOffset,
}: {
  innerRadius: number
  outerRadius: number
  color: string
  opacity: number
  yOffset: number
}) {
  const geometry = useMemo(() => {
    const shape = new THREE.Shape()
    const segments = 64

    // Outer circle
    for (let i = 0; i <= segments; i++) {
      const angle = (i / segments) * Math.PI * 2
      const x = Math.cos(angle) * outerRadius
      const y = Math.sin(angle) * outerRadius
      if (i === 0) shape.moveTo(x, y)
      else shape.lineTo(x, y)
    }

    // Inner circle (hole)
    const hole = new THREE.Path()
    for (let i = 0; i <= segments; i++) {
      const angle = (i / segments) * Math.PI * 2
      const x = Math.cos(angle) * innerRadius
      const y = Math.sin(angle) * innerRadius
      if (i === 0) hole.moveTo(x, y)
      else hole.lineTo(x, y)
    }
    shape.holes.push(hole)

    const geom = new THREE.ShapeGeometry(shape, segments)
    // Rotate to lie in XZ plane
    geom.rotateX(-Math.PI / 2)
    return geom
  }, [innerRadius, outerRadius])

  return (
    <mesh geometry={geometry} position={[0, yOffset, 0]}>
      <meshBasicMaterial
        color={color}
        transparent
        opacity={opacity}
        side={THREE.DoubleSide}
        depthWrite={false}
      />
    </mesh>
  )
}

/**
 * Thin circle line at a given radius.
 */
function CircleLine({
  radius,
  color,
  opacity,
  yOffset,
  dashed,
}: {
  radius: number
  color: string
  opacity: number
  yOffset: number
  dashed?: boolean
}) {
  const points = useMemo(() => {
    const pts: [number, number, number][] = []
    const segments = 64
    for (let i = 0; i <= segments; i++) {
      const angle = (i / segments) * Math.PI * 2
      pts.push([
        Math.cos(angle) * radius,
        yOffset,
        Math.sin(angle) * radius,
      ])
    }
    return pts
  }, [radius, yOffset])

  return (
    <Line
      points={points}
      color={color}
      transparent
      opacity={opacity}
      lineWidth={1}
      dashed={dashed}
      dashSize={dashed ? 0.3 : undefined}
      gapSize={dashed ? 0.2 : undefined}
    />
  )
}

export default function HabitableZoneRing({
  data,
  yOffset = -0.05,
}: HabitableZoneRingProps) {
  const hz = data.habitable_zone
  if (!hz) return null

  const innerAU = hz.runaway_greenhouse_au ?? 0
  const outerAU = hz.max_greenhouse_au ?? 0

  if (innerAU <= 0 || outerAU <= innerAU) return null

  const innerR = distanceScale(innerAU)
  const outerR = distanceScale(outerAU)

  const condensation = data.condensation_lines

  return (
    <group>
      {/* Main habitable zone ring — green tint */}
      <FlatRing
        innerRadius={innerR}
        outerRadius={outerR}
        color="#22aa44"
        opacity={0.08}
        yOffset={yOffset}
      />

      {/* Inner edge line */}
      <CircleLine
        radius={innerR}
        color="#22aa44"
        opacity={0.3}
        yOffset={yOffset}
      />

      {/* Outer edge line */}
      <CircleLine
        radius={outerR}
        color="#22aa44"
        opacity={0.3}
        yOffset={yOffset}
      />

      {/* Condensation lines */}
      {condensation?.water_snow_line_au && (
        <CircleLine
          radius={distanceScale(condensation.water_snow_line_au)}
          color="#4488cc"
          opacity={0.2}
          yOffset={yOffset}
          dashed
        />
      )}

      {condensation?.rock_line_au && (
        <CircleLine
          radius={distanceScale(condensation.rock_line_au)}
          color="#cc6633"
          opacity={0.2}
          yOffset={yOffset}
          dashed
        />
      )}
    </group>
  )
}
