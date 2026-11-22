import { browserClimateAssets, type ClimateTrialResult, type SavedBrowserEbm } from '../api/climateTrials'
import { composeSplitMesh, isSplitFields, isSplitGeometry } from '../api/meshColumns'
import { decodeMonthlyClimate } from '../api/monthlyClimate'
import { decodeYearlyClimate } from '../api/yearlyClimate'
import { decodeMsgpackUrl } from '../workers/msgpackClient'

const identifier = /^[\w-][\w.-]{0,99}$/
const fingerprint = /^[a-f0-9]{64}$/
const maxAssetBytes = 32 * 2 ** 20

export function restoreBrowserEbm(id: string, value: unknown, assets: SavedBrowserEbm['assets']): SavedBrowserEbm {
  const metadata = value as SavedBrowserEbm['metadata'] | null
  if (!metadata || metadata.id !== id || metadata.format !== 1 || metadata.solver !== 'ebm' ||
      typeof metadata.planet !== 'string' || !identifier.test(metadata.planet) ||
      !(metadata.branch === null || (typeof metadata.branch === 'string' && identifier.test(metadata.branch))) ||
      !Number.isFinite(Date.parse(metadata.saved_at)) || !Number.isSafeInteger(metadata.cells) ||
      metadata.cells < 1 || metadata.cells > 20_000 || !Number.isFinite(metadata.elapsed_seconds) || metadata.elapsed_seconds < 0 ||
      !metadata.inputs || !fingerprint.test(metadata.inputs.mesh_sha256) || !fingerprint.test(metadata.inputs.config_sha256) ||
      !Number.isFinite(metadata.inputs.radius_km) || metadata.inputs.radius_km <= 0 ||
      !metadata.inputs.forcing || !['axial_tilt_deg', 'rotation_period_days', 'albedo', 'greenhouse_warming_k']
        .every(key => Number.isFinite(metadata.inputs.forcing[key as keyof typeof metadata.inputs.forcing])) ||
      metadata.surface?.planet_id !== metadata.planet || metadata.surface.projection !== 'equirectangular' ||
      ![metadata.surface.width, metadata.surface.height].every(value => Number.isSafeInteger(value) && value > 0 && value <= 8192) ||
      ![metadata.surface.elevation_min_m, metadata.surface.elevation_max_m, metadata.surface.sea_level_m].every(Number.isFinite) ||
      browserClimateAssets.some(key => !assets[key].size || assets[key].size > maxAssetBytes) ||
      (assets.terrain && (!assets.terrain.size || assets.terrain.size > maxAssetBytes))) {
    throw new Error('Invalid browser climate result')
  }
  return { metadata, assets }
}

export async function loadSavedBrowserEbm({ metadata, assets }: SavedBrowserEbm): Promise<ClimateTrialResult> {
  const geometryUrl = URL.createObjectURL(assets.geometry)
  const fieldsUrl = URL.createObjectURL(assets.fields)
  try {
    const [geometry, fields, monthlyBytes, yearlyBytes] = await Promise.all([
      decodeMsgpackUrl(geometryUrl, true, maxAssetBytes), decodeMsgpackUrl(fieldsUrl, true, maxAssetBytes),
      assets.monthly.arrayBuffer(), assets.yearly.arrayBuffer(),
    ])
    const mesh = isSplitGeometry(geometry) && isSplitFields(fields) &&
      geometry.num_cells === metadata.cells && fields.num_cells === metadata.cells
      ? composeSplitMesh(geometry, fields) : null
    const monthly = decodeMonthlyClimate(monthlyBytes)
    const yearly = decodeYearlyClimate(yearlyBytes)
    if (!mesh || [monthly.numCells, yearly.numCells].some(cells => cells !== metadata.cells)) throw new Error('Invalid climate trial grid')
    return { mesh, monthly, yearly, forcing: metadata.inputs.forcing, saved: { metadata, elevation: assets.elevation } }
  } finally {
    URL.revokeObjectURL(geometryUrl)
    URL.revokeObjectURL(fieldsUrl)
  }
}
