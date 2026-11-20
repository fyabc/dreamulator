import { describe, expect, it } from 'vitest'
import { nativeTerrainSpacing, recommendTerrain, terrainRecipe } from './terrainRecommendation'

describe('browser terrain processing recommendation', () => {
  it('leaves the choice to the author when native spacing is unknown', () => {
    for (const value of ['', ' ', '0', '-1', 'Infinity', 'abc', '1e500']) {
      expect(nativeTerrainSpacing(value)).toBeNull()
      expect(recommendTerrain(nativeTerrainSpacing(value), 23, 46 / 512)).toBeNull()
    }
  })

  it('recommends redraw for a coarse input and leaves finer inputs unselected', () => {
    expect(recommendTerrain(nativeTerrainSpacing('50'), 23, 46 / 512)).toEqual({ method: 'redraw', reason: 'coarse' })
    expect(recommendTerrain(nativeTerrainSpacing('0.36'), 23, 46 / 512)).toEqual({ method: null, reason: 'detail' })
    expect(recommendTerrain(nativeTerrainSpacing('0.03'), 23, 46 / 512)).toEqual({ method: null, reason: 'dense' })
  })

  it('uses the conditioning and output pitches of the actual selection', () => {
    expect(recommendTerrain(23, 23, 0.09)?.method).toBe('redraw')
    expect(recommendTerrain(23, 23.2, 0.09)?.method).toBeNull()
    expect(recommendTerrain(0.09, 23, 0.09)?.reason).toBe('dense')
    expect(recommendTerrain(0.09, 23, 0.089)?.reason).toBe('detail')
  })

  it('requires a usable native spacing only for the blend', () => {
    expect(terrainRecipe('blend', null, 0.09)).toBeNull()
    expect(terrainRecipe('blend', 0.09, 0.09)).toBeNull()
    expect(terrainRecipe('blend', 0.36, 0.09)).toEqual({ method: 'blend', preserveKm: 1.44, seed: 42, residualGain: 1 })
    expect(terrainRecipe('enhanced', null, 0.09)).toEqual({ method: 'enhanced', seed: 42, residualGain: 2 })
    expect(terrainRecipe(null, 0.36, 0.09)).toBeNull()
  })

  it('validates and captures only the parameters used by the selected method', () => {
    expect(terrainRecipe('blend', 0.36, 0.09, { seed: '8', wavelength: '0.8', gain: '3' }))
      .toEqual({ method: 'blend', preserveKm: 0.8, seed: 8, residualGain: 1 })
    expect(terrainRecipe('enhanced', null, 0.09, { seed: '0', gain: '2.5', wavelength: '-1' }))
      .toEqual({ method: 'enhanced', seed: 0, residualGain: 2.5 })
    expect(terrainRecipe('blend', 0.36, 0.09, { wavelength: '0.35' })).toBeNull()
    expect(terrainRecipe('enhanced', null, 0.09, { gain: '3.1' })).toBeNull()
    for (const seed of ['-1', '1.1', '2147483648', 'Infinity']) {
      expect(terrainRecipe('redraw', null, 0.09, { seed })).toBeNull()
    }
  })
})
