import type { VoronoiCell } from './types'

export type InspectedCell = Pick<VoronoiCell, 'id' | 'lon' | 'lat' | 'elevation'> & Partial<VoronoiCell>

export function trialTerrainCell({ id, lon, lat, elevation, area_km2, water_class, is_lake }: VoronoiCell): InspectedCell {
  return { id, lon, lat, elevation, area_km2, water_class, is_lake }
}
