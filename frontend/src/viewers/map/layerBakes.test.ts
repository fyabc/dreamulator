import { describe, expect, it } from 'vitest'
import { bakeMonthlyLayer, getLayerTextures } from './layerBakes'
import type { CVTMesh, VoronoiCell } from './types'
import { temperatureColor } from './utils/colorScales'

describe('model-grid ocean climate layers', () => {
  it('uses stored annual and monthly values, with transparent missing cells', () => {
    const mesh: CVTMesh = { num_cells: 2, seed: 1, vertices: [], regions: [], cells: [
      { id: 7, elevation: -4000, water_class: 'ocean', temperature_C: 25, precipitation_mm: 80,
        koppen_class: 'Ocean', temperature_coldest_month_C: 22 },
      { id: 8, elevation: -4000, water_class: 'ocean' },
    ] as VoronoiCell[] }
    const cellIdMap = new Uint32Array([7, 8])
    const annual = getLayerTextures({ cvtMesh: mesh, elevation: new Float32Array([0, 0]), width: 2,
      height: 1, cellIdMap, seaLevel: 0, elevMinM: -4000, elevMaxM: 4000,
      waterDepthFactor: 1, flipHorizontal: false })
    expect(Array.from(annual.temperature.image.data)).toEqual([...temperatureColor(25), 255, 0, 0, 0, 0])
    expect(annual.precipitation.image.data[3]).toBe(255)
    expect(annual.precipitation.image.data[7]).toBe(0)
    expect(Array.from(annual.koppen.image.data.slice(0, 4))).toEqual([22, 133, 130, 255])

    const monthly = { numCells: 2, months: 1, tMonthly: new Float32Array([22, NaN]), pMonthly: new Float32Array([4, NaN]),
      temperatureRangeC: [22, 22] as [number, number], precipitationRangeMm: [4, 4] as [number, number] }
    const temperature = bakeMonthlyLayer(monthly, 0, 'temperature', mesh, cellIdMap, 2, 1, false)
    const precipitation = bakeMonthlyLayer(monthly, 0, 'precipitation', mesh, cellIdMap, 2, 1, false)
    expect(Array.from(temperature.image.data)).toEqual([...temperatureColor(22), 255, 0, 0, 0, 0])
    expect(precipitation.image.data[3]).toBe(255)
    expect(precipitation.image.data[7]).toBe(0)
  })
})
