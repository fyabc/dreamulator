import type { LonLat } from './mapCoords'

export function lonLatToGlobePosition({ lon, lat }: LonLat, radius: number): [number, number, number] {
  const longitude = lon * Math.PI / 180
  const latitude = lat * Math.PI / 180
  const radial = radius * Math.cos(latitude)
  return [radial * Math.cos(longitude), radius * Math.sin(latitude), -radial * Math.sin(longitude)]
}
