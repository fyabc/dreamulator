/**
 * OrbitLine — renders an orbital ellipse path from Keplerian elements.
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
  color = '#2a2a5a',
  opacity = 0.5,
}: OrbitLineProps) {
  const points = useMemo(() => {
    return computeOrbitPath(orbit, 128)
  }, [orbit])

  // Convert to flat array of [x,y,z] tuples for drei Line
  const linePoints = useMemo(() => {
    return points.map(([x, y, z]) => [x, y, z] as [number, number, number])
  }, [points])

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
