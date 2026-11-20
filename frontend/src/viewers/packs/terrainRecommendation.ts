export type TerrainRecipe = { seed: number; residualGain: number } &
  ({ method: 'redraw' | 'enhanced' } | { method: 'blend'; preserveKm: number })
export type TerrainMethod = TerrainRecipe['method']
export type TerrainRecommendation = { method: 'redraw'; reason: 'coarse' } | { method: null; reason: 'detail' | 'dense' }

export const defaultTerrainSeed = 42
export const maxTerrainSeed = 2 ** 31 - 1
export const defaultEnhancedGain = 2
export const minEnhancedGain = 1
export const maxEnhancedGain = 3

export function terrainSeed(value: string) {
  if (!value.trim()) return defaultTerrainSeed
  const seed = Number(value)
  return Number.isInteger(seed) && seed >= 0 && seed <= maxTerrainSeed ? seed : null
}

export function enhancedTerrainGain(value: string) {
  if (!value.trim()) return defaultEnhancedGain
  const gain = Number(value)
  return gain >= minEnhancedGain && gain <= maxEnhancedGain ? gain : null
}

export function terrainRecipe(method: TerrainMethod | null | undefined, nativeKm: number | null, outputKm: number, {
  seed = '', gain = '', wavelength = '',
}: { seed?: string; gain?: string; wavelength?: string } = {}): TerrainRecipe | null {
  const parsedSeed = terrainSeed(seed)
  if (parsedSeed === null) return null
  const residualGain = method === 'enhanced' ? enhancedTerrainGain(gain) : 1
  if (residualGain === null) return null
  if (method === 'redraw' || method === 'enhanced') return { method, seed: parsedSeed, residualGain }
  if (method !== 'blend' || nativeKm === null || nativeKm <= outputKm) return null
  const preserveKm = wavelength.trim() ? Number(wavelength) : nativeKm * 4
  if (Number.isFinite(preserveKm) && preserveKm >= 4 * outputKm) return { method, preserveKm, seed: parsedSeed, residualGain }
  return null
}

export function nativeTerrainSpacing(value: string) {
  const spacing = Number(value)
  return Number.isFinite(spacing) && spacing > 0 ? spacing : null
}

export function recommendTerrain(nativeKm: number | null, modelKm: number, outputKm: number): TerrainRecommendation | null {
  if (nativeKm === null) return null
  if (nativeKm <= outputKm) return { method: null, reason: 'dense' }
  if (nativeKm < modelKm) return { method: null, reason: 'detail' }
  return { method: 'redraw', reason: 'coarse' }
}
