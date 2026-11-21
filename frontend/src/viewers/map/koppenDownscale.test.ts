import { describe, expect, it } from 'vitest'
import { classifyKoppenLand, displayKoppenClass, hasKoppenMonths, koppenRasterPixels, marineKoppenBands, type KoppenRasterInput } from './koppenDownscale'
import { KOPPEN_COLORS } from './utils/colorScales'

const months = (value: number) => new Float32Array(12).fill(value)
const rgba = (code: string) => {
  const rgb = parseInt(({ ...KOPPEN_COLORS, ...marineKoppenBands } as Record<string, string>)[code].slice(1), 16)
  return [(rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255, 255]
}

describe('Köppen display downscaling', () => {
  it('preserves Dreamulator boundaries, including seasonality and polar priority', () => {
    const classify = (temperature: ArrayLike<number>, rain: ArrayLike<number>) =>
      classifyKoppenLand(Float64Array.from(temperature), Float64Array.from(rain), new Uint8Array(12))
    const mild = [4, 5, 8, 12, 16, 20, 23, 22, 17, 12, 8, 5]
    const drySummer = [90, 80, 75, 50, 25, 12, 2, 5, 20, 75, 90, 98]
    expect(classify(mild, drySummer)).toBe('Csa')
    expect(classify(mild.map((_, index) => mild[(index + 6) % 12]),
      drySummer.map((_, index) => drySummer[(index + 6) % 12]))).toBe('Csa')
    expect(classify(mild, months(100))).toBe('Cfa')
    expect(classify(months(8), months(0))).toBe('ET')
    expect(classify(months(19), months(8))).toBe('BWh')
    expect(classify(months(24), months(80))).toBe('Af')
    expect(classify([-39, -29, -18, -5, 2, 8, 12, 11, 5, -6, -15, -30], months(70))).toBe('Dfd')
  })

  const input: KoppenRasterInput = {
    cells: [{ id: 37, elevation: 500, koppen_class: 'Cfa' }], cellIds: new Uint32Array([37]),
    meshWidth: 1, meshHeight: 1, width: 4, height: 1, seaLevelM: 0, native: null,
    tMonthly: months(21), pMonthly: months(100),
  }

  it('classifies the interpolated and elevation-corrected temperatures, not class colours', () => {
    const native = { elevation: new Float32Array([0, 0.15, 0.65, 1]), width: 4, height: 1, minM: -100, maxM: 3900, seaLevelM: 0 }
    expect(Array.from(koppenRasterPixels({ ...input, native })!)).toEqual([
      ...rgba('Ocean'), ...rgba('Af'), ...rgba('Cfb'), ...rgba('ET'),
    ])
  })

  it('interpolates temperature and rain before classification, including across the dateline', () => {
    const pixels = koppenRasterPixels({ ...input, meshWidth: 2,
      cells: [...input.cells, { id: 96, elevation: 500, koppen_class: 'BWh' }], cellIds: new Uint32Array([37, 96]),
      tMonthly: new Float32Array([...months(26), ...months(20)]), pMonthly: new Float32Array([...months(90), ...months(0)]),
    })
    expect(Array.from(pixels!)).toEqual([...rgba('Af'), ...rgba('Af'), ...rgba('BWh'), ...rgba('BWh')])
  })

  it('classifies marine temperatures after interpolation without mixing land and ocean regimes', () => {
    const sea = { id: 37, elevation: -500, water_class: 'ocean', koppen_class: 'Ocean' }
    const land = { id: 96, elevation: 500, water_class: 'land', koppen_class: 'EF' }
    const native = { elevation: new Float32Array([0, 0, 1, 1]), width: 4, height: 1, minM: -500, maxM: 500, seaLevelM: 0 }
    const pixels = koppenRasterPixels({ ...input, native, meshWidth: 2,
      cells: [sea, land], cellIds: new Uint32Array([37, 96]),
      tMonthly: new Float32Array([...months(25), ...months(-10)]), pMonthly: new Float32Array([...months(NaN), ...months(80)]),
    })
    expect(Array.from(pixels!)).toEqual([...rgba('SeaTrop'), ...rgba('SeaTrop'), ...rgba('EF'), ...rgba('EF')])
    expect(displayKoppenClass({ ...sea, temperature_coldest_month_C: 18 }, 0)).toBe('SeaTemp')
    expect(displayKoppenClass({ ...sea, temperature_coldest_month_C: 18.5 }, 0)).toBe('SeaTrop')
    expect(displayKoppenClass(sea, 0)).toBe('Ocean')
    expect(displayKoppenClass({ ...land, temperature_coldest_month_C: 18.5 }, 0)).toBe('EF')
  })

  it('requires paired twelve-month inputs and leaves an incomplete world on the model grid', () => {
    const data = { ...input, numCells: 1, months: 12,
      temperatureRangeC: [21, 21] as [number, number], precipitationRangeMm: [100, 100] as [number, number] }
    expect(hasKoppenMonths(data, 1)).toBe(true)
    expect(hasKoppenMonths({ ...data, pMonthly: new Float32Array(0) }, 1)).toBe(false)
    expect(hasKoppenMonths({ ...data, months: 13 }, 1)).toBe(false)
    expect(koppenRasterPixels({ ...input, pMonthly: months(NaN) })).toBeNull()
  })
})
