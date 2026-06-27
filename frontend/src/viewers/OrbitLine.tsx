/**
 * OrbitLine — renders an orbital ellipse path in real AU coordinates.
 */

import { useMemo } from 'react'
import { Line } from '@react-three/drei'
import { computeOrbitPath } from './utils/scale'

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

interface OrbitLineProps {
  orbit: OrbitalElementsData
  color?: string
  opacity?: number
}

export default function OrbitLine({
  orbit,
  color = '#3a3a7a',
  opacity = 0.35,
}: OrbitLineProps) {
  const linePoints = useMemo(() => {
    return computeOrbitPath(orbit, 128) as [number, number, number][]
  }, [orbit])

  return (
    <Line
      points={linePoints}
      color={color}
      lineWidth={1}
      transparent
      opacity={opacity}
    />
  )
}
