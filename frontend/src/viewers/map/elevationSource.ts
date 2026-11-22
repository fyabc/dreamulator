import type { MapMetadata } from './types'

export type TerrainSource = 'raster' | 'mesh'

export function hasOriginalTerrain(meta: MapMetadata | undefined) {
  return Boolean(meta?.elevation_import || meta?.pipeline_version === 'etopo1-import')
}

export function terrainSourceFor(meta: MapMetadata | undefined, hasMesh: boolean, hasRaster: boolean,
  requested: string | null): TerrainSource {
  const original = hasRaster && hasOriginalTerrain(meta)
  if (hasMesh && (!original || requested === 'mesh')) return 'mesh'
  return 'raster'
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
