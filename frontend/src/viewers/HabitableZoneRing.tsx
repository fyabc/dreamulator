/**
 * HabitableZoneRing — renders a translucent ring showing the habitable zone
 * and condensation line markers, in real AU coordinates.
 */

import { useMemo } from 'react'
import * as THREE from 'three'
import { Line } from '@react-three/drei'

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
  yOffset?: number
}

/**
 * Flat ring between inner and outer radii (both in AU).
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
    const segments = 96

    for (let i = 0; i <= segments; i++) {
      const angle = (i / segments) * Math.PI * 2
      const x = Math.cos(angle) * outerRadius
      const y = Math.sin(angle) * outerRadius
      if (i === 0) shape.moveTo(x, y)
      else shape.lineTo(x, y)
    }

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
 * Thin circle line at a given AU radius.
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
    const segments = 96
    for (let i = 0; i <= segments; i++) {
      const angle = (i / segments) * Math.PI * 2
      pts.push([Math.cos(angle) * radius, yOffset, Math.sin(angle) * radius])
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
      dashSize={dashed ? radius * 0.04 : undefined}
      gapSize={dashed ? radius * 0.025 : undefined}
    />
  )
}

export default function HabitableZoneRing({
  data,
  yOffset = -0.002,
}: HabitableZoneRingProps) {
  const hz = data.habitable_zone
  if (!hz) return null

  const innerAU = hz.runaway_greenhouse_au ?? 0
  const outerAU = hz.max_greenhouse_au ?? 0

  if (innerAU <= 0 || outerAU <= innerAU) return null

  const condensation = data.condensation_lines

  return (
    <group>
      {/* Habitable zone fill */}
      <FlatRing
        innerRadius={innerAU}
        outerRadius={outerAU}
        color="#22aa44"
        opacity={0.07}
        yOffset={yOffset}
      />

      {/* HZ boundary lines */}
      <CircleLine radius={innerAU} color="#22aa44" opacity={0.25} yOffset={yOffset} />
      <CircleLine radius={outerAU} color="#22aa44" opacity={0.25} yOffset={yOffset} />

      {/* Condensation lines */}
      {condensation?.water_snow_line_au && (
        <CircleLine
          radius={condensation.water_snow_line_au}
          color="#4488cc"
          opacity={0.15}
          yOffset={yOffset}
          dashed
        />
      )}

      {condensation?.rock_line_au && (
        <CircleLine
          radius={condensation.rock_line_au}
          color="#cc6633"
          opacity={0.15}
          yOffset={yOffset}
          dashed
        />
      )}
    </group>
  )
}
