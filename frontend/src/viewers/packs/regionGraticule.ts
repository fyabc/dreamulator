import { degPerKm, kmToLonLat, lonLatToKm, wrapLon, type PackWindow } from './packCoords'

type Position = [number, number]

function clipSegment(from: Position, to: Position, halfWidth: number, halfHeight: number): [Position, Position] | null {
  const dx = to[0] - from[0]
  const dy = to[1] - from[1]
  let start = 0
  let end = 1
  for (const [direction, distance] of [[-dx, from[0] + halfWidth], [dx, halfWidth - from[0]],
    [-dy, from[1] + halfHeight], [dy, halfHeight - from[1]]]) {
    if (direction === 0 && distance < 0) return null
    if (direction < 0) start = Math.max(start, distance / direction)
    if (direction > 0) end = Math.min(end, distance / direction)
  }
  return start < end ? [[from[0] + start * dx, from[1] + start * dy], [from[0] + end * dx, from[1] + end * dy]] : null
}

export function projectedRegionGraticule(window: PackWindow) {
  const halfWidth = window.extentKmX / 2
  const halfHeight = window.extentKmY / 2
  const perimeter = Array.from({ length: 33 }, (_, index) => {
    const along = index / 16 - 1
    return [kmToLonLat(halfWidth * along, halfHeight, window), kmToLonLat(halfWidth * along, -halfHeight, window),
      kmToLonLat(halfWidth, halfHeight * along, window), kmToLonLat(-halfWidth, halfHeight * along, window)]
  }).flat()
  const containsPole = (lat: number) => {
    const { x, y } = lonLatToKm({ lat, lon: window.centerLon }, window)
    return Math.abs(x) <= halfWidth && Math.abs(y) <= halfHeight
  }
  const north = containsPole(90)
  const south = containsPole(-90)
  const latitudes = perimeter.map(point => point.lat)
  const longitudes = perimeter.map(point => wrapLon(point.lon - window.centerLon))
  const margin = Math.max(0.02, Math.max(halfWidth, halfHeight) * degPerKm(window) / 16)
  const minLat = south ? -90 : Math.max(-90, Math.min(...latitudes) - margin)
  const maxLat = north ? 90 : Math.min(90, Math.max(...latitudes) + margin)
  const minLon = window.centerLon + (north || south ? -180 : Math.max(-180, Math.min(...longitudes) - margin))
  const maxLon = window.centerLon + (north || south ? 180 : Math.min(180, Math.max(...longitudes) + margin))
  const step = [0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 45, 60]
    .find(candidate => Math.max(maxLat - minLat, maxLon - minLon) / candidate <= 8) ?? 60

  function paths(from: number, to: number, latitude: boolean, coordinate: number) {
    const runs: Position[][] = []
    let run: Position[] | undefined
    let previous: Position | undefined
    for (let index = 0; index <= 128; index++) {
      const value = from + (to - from) * index / 128
      const { x, y } = lonLatToKm(latitude ? { lat: coordinate, lon: value } : { lat: value, lon: coordinate }, window)
      const next: Position = [x, y]
      const edge = previous && Math.hypot(x - previous[0], y - previous[1]) < Math.hypot(halfWidth, halfHeight)
        ? clipSegment(previous, next, halfWidth, halfHeight) : null
      if (!edge) run = undefined
      else {
        if (!run) { run = [edge[0]]; runs.push(run) }
        run.push(edge[1])
      }
      previous = next
    }
    return runs
  }

  const lines: { paths: Position[][]; coordinate: number; latitude: boolean }[] = []
  for (let index = Math.ceil(minLat / step); index * step < maxLat; index++) {
    const coordinate = index * step
    if (Math.abs(coordinate) < 90) lines.push({ paths: paths(minLon, maxLon, true, coordinate), coordinate, latitude: true })
  }
  for (let index = Math.ceil(minLon / step); index * step < maxLon; index++) {
    const coordinate = index * step
    lines.push({ paths: paths(minLat, maxLat, false, coordinate), coordinate: wrapLon(coordinate), latitude: false })
  }
  return lines.filter(line => line.paths.length)
}
