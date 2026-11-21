import type { MonthlyClimateData } from '../../api/monthlyClimate'
import { climateRasterSurface, climateSourceDimensions, temperatureLapseCPerM, type ClimateRasterTerrain } from './climateDownscale'
import type { VoronoiCell } from './types'
import { KOPPEN_COLORS } from './utils/colorScales'

const MONTHS = 12

export function hasKoppenMonths(data: MonthlyClimateData | null, cellCount: number) {
  return data != null && cellCount > 0 && data.numCells === cellCount && data.months === MONTHS &&
    data.tMonthly.length === cellCount * MONTHS && data.pMonthly.length === cellCount * MONTHS
}

export function classifyKoppenLand(temperature: Float64Array, rain: Float64Array, order: Uint8Array) {
  let coldest = Infinity, hottest = -Infinity, temperatureSum = 0, warmMonths = 0, annualRain = 0, driest = Infinity
  for (let month = 0; month < MONTHS; month++) {
    const temp = temperature[month], precip = rain[month]
    coldest = Math.min(coldest, temp)
    hottest = Math.max(hottest, temp)
    temperatureSum += temp
    warmMonths += Number(temp >= 10)
    annualRain += precip
    driest = Math.min(driest, precip)

    let position = month
    while (position > 0 && temperature[order[position - 1]] > temp) {
      order[position] = order[position - 1]
      position--
    }
    order[position] = month
  }
  if (hottest < 10) return hottest > 0 ? 'ET' : 'EF'

  let summerRain = 0, winterRain = 0, drySummer = Infinity, wetSummer = 0, dryWinter = Infinity, wetWinter = 0
  for (let rank = 0; rank < MONTHS / 2; rank++) {
    const summer = rain[order[rank + MONTHS / 2]], winter = rain[order[rank]]
    summerRain += summer
    winterRain += winter
    drySummer = Math.min(drySummer, summer)
    wetSummer = Math.max(wetSummer, summer)
    dryWinter = Math.min(dryWinter, winter)
    wetWinter = Math.max(wetWinter, winter)
  }
  const mean = temperatureSum / MONTHS
  const offset = summerRain > 0.7 * annualRain ? 280 : winterRain > 0.7 * annualRain ? 0 : 140
  const aridity = Math.max(20 * mean + offset, 1)
  if (annualRain <= aridity) return `B${annualRain <= aridity / 2 ? 'W' : 'S'}${mean > 18 ? 'h' : 'k'}`
  if (coldest > 18) return driest > 60 ? 'Af' : driest >= 100 - annualRain / 25 ? 'Am' : 'Aw'

  const temperate = coldest > -3
  const season = drySummer < wetWinter / 3 && (!temperate || drySummer < 40) ? 's' : dryWinter < wetSummer / 10 ? 'w' : 'f'
  const summer = !temperate && coldest < -38 ? 'd' : hottest > 22 ? 'a' : warmMonths >= 4 ? 'b' : 'c'
  return `${temperate ? 'C' : 'D'}${season}${summer}`
}

export interface KoppenRasterInput {
  cells: Pick<VoronoiCell, 'id' | 'elevation' | 'water_class' | 'koppen_class'>[]
  cellIds: Uint32Array
  meshWidth: number
  meshHeight: number
  width: number
  height: number
  seaLevelM: number
  native: ClimateRasterTerrain | null
  tMonthly: Float32Array
  pMonthly: Float32Array
}

export function koppenRasterPixels({
  cells, cellIds, meshWidth, meshHeight, width, height, seaLevelM, native, tMonthly, pMonthly,
}: KoppenRasterInput) {
  const byId = new Map(cells.map((cell, index) => [cell.id, index]))
  const isLand = cells.map(cell => cell.water_class != null ? cell.water_class !== 'ocean' : cell.elevation >= seaLevelM)
  const lapse = cells.map((_, index) => {
    if (!isLand[index]) return NaN
    let rain = 0
    for (let month = index * MONTHS; month < (index + 1) * MONTHS; month++) {
      if (!Number.isFinite(tMonthly[month]) || !Number.isFinite(pMonthly[month])) return NaN
      rain += Math.max(0, pMonthly[month])
    }
    return temperatureLapseCPerM(rain)
  })
  if (!lapse.some(Number.isFinite)) return null

  const sourceCell = (x: number, y: number) => byId.get(cellIds[y * meshWidth + x]) ?? -1
  const { gridWidth, gridHeight } = climateSourceDimensions(cells.length, meshWidth, meshHeight)
  const grid = new Int32Array(gridWidth * gridHeight)
  for (let row = 0; row < gridHeight; row++) {
    for (let column = 0; column < gridWidth; column++) {
      const index = sourceCell(Math.round((column + 0.5) * (meshWidth - 1) / gridWidth),
        Math.round((row + 0.5) * (meshHeight - 1) / gridHeight))
      grid[row * gridWidth + column] = Number.isFinite(lapse[index]) ? index : -1
    }
  }

  const colors = new Map(Object.entries(KOPPEN_COLORS).map(([code, hex]) => [code, parseInt(hex.slice(1), 16)]))
  const pixels = new Uint8Array(width * height * 4)
  const surface = native ? climateRasterSurface(native, width, height) : null
  const modelHeight = cells.map(cell => Math.max(0, cell.elevation - seaLevelM))
  const temperature = new Float64Array(MONTHS), rain = new Float64Array(MONTHS), order = new Uint8Array(MONTHS)
  const neighbors = new Int32Array(4), weights = new Float64Array(4)
  const columns = Array.from({ length: width }, (_, column) => {
    const position = (column + 0.5) * gridWidth / width - 0.5
    const west = Math.floor(position)
    return { west: (west + gridWidth) % gridWidth, east: (west + 1) % gridWidth, fraction: position - west,
      meshX: Math.floor((column + 0.5) * meshWidth / width) }
  })
  for (let row = 0; row < height; row++) {
    const position = Math.max(0, Math.min(gridHeight - 1, (row + 0.5) * gridHeight / height - 0.5))
    const north = Math.floor(position), south = Math.min(north + 1, gridHeight - 1), fraction = position - north
    const meshY = Math.floor((row + 0.5) * meshHeight / height)
    for (let column = 0; column < width; column++) {
      const { west, east, fraction: eastWeight, meshX } = columns[column]
      const index = sourceCell(meshX, meshY)
      if (!surface && index < 0) continue
      const fineHeight = surface?.(column, row)
      let code = 'Ocean'
      if (surface ? Number.isFinite(fineHeight) : isLand[index]) {
        neighbors[0] = grid[north * gridWidth + west]
        neighbors[1] = grid[north * gridWidth + east]
        neighbors[2] = grid[south * gridWidth + west]
        neighbors[3] = grid[south * gridWidth + east]
        weights[0] = (1 - eastWeight) * (1 - fraction)
        weights[1] = eastWeight * (1 - fraction)
        weights[2] = (1 - eastWeight) * fraction
        weights[3] = eastWeight * fraction
        let weightSum = 0, heightSum = 0, lapseSum = 0
        temperature.fill(0)
        rain.fill(0)
        for (let corner = 0; corner < neighbors.length; corner++) {
          const neighbor = neighbors[corner], weight = weights[corner]
          if (neighbor < 0 || weight === 0) continue
          weightSum += weight
          heightSum += weight * modelHeight[neighbor]
          lapseSum += weight * lapse[neighbor]
          const start = neighbor * MONTHS
          for (let month = 0; month < MONTHS; month++) {
            temperature[month] += weight * tMonthly[start + month]
            rain[month] += weight * Math.max(0, pMonthly[start + month])
          }
        }
        if (weightSum === 0) {
          code = isLand[index] ? cells[index].koppen_class ?? '' : ''
        } else {
          const correction = fineHeight == null ? 0 : lapseSum / weightSum * (fineHeight - heightSum / weightSum)
          for (let month = 0; month < MONTHS; month++) {
            temperature[month] = temperature[month] / weightSum + correction
            rain[month] /= weightSum
          }
          code = classifyKoppenLand(temperature, rain, order)
        }
      }
      const color = colors.get(code)
      if (color == null) continue
      const offset = ((height - 1 - row) * width + column) * 4
      pixels[offset] = color >> 16
      pixels[offset + 1] = color >> 8
      pixels[offset + 2] = color
      pixels[offset + 3] = 255
    }
  }
  return pixels
}
