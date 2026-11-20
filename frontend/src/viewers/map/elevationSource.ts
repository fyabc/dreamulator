import type { MapMetadata } from './types'

export type TerrainSource = 'raster' | 'gray' | 'mesh'

export function terrainSourceFor(meta: MapMetadata | undefined, hasMesh: boolean, requested: string | null): TerrainSource {
  if (!hasMesh) return meta?.elevation_import && requested === 'gray' ? 'gray' : 'raster'
  if (!meta?.elevation_import || requested === 'mesh') return 'mesh'
  return requested === 'gray' ? 'gray' : 'raster'
}

export function meshTextureDimensions(meta: MapMetadata | null | undefined) {
  const width = meta?.width ?? 2048
  const height = meta?.height ?? 1024
  const scale = meta?.elevation_import ? Math.min(1, 2048 / width, 1024 / height) : 1
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) }
}

export function importedRasterSpacingKm(meta: MapMetadata, width: number, height: number, radiusKm: number) {
  const provenance = meta.elevation_import
  if (!provenance || provenance.was_resampled || width !== 2 * height || height < 2 ||
    provenance.source_resolution[0] !== width || provenance.source_resolution[1] !== height ||
    provenance.output_resolution[0] !== width || provenance.output_resolution[1] !== height) return null
  return Math.PI * radiusKm / height
}
