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
  /** Absolute position of the parent body — orbit path is translated by this */
  parentPosition?: [number, number, number] | null
  color?: string
  opacity?: number
}

export default function OrbitLine({
  orbit,
  parentPosition,
  color = '#3a3a7a',
  opacity = 0.35,
}: OrbitLineProps) {
  const linePoints = useMemo(() => {
    const path = computeOrbitPath(orbit, 128) as [number, number, number][]
    if (!parentPosition) return path
    // Translate orbit path to parent body's absolute position
    return path.map(
      ([x, y, z]) =>
        [x + parentPosition[0], y + parentPosition[1], z + parentPosition[2]] as [
          number,
          number,
          number,
        ],
    )
  }, [orbit, parentPosition])

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
