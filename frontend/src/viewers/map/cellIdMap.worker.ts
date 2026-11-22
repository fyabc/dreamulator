/**
 * Cell-ID map worker: nearest-cell lookup for every pixel of the equirectangular
 * texture.  This is the O(width × height × log N) pass that used to block the
 * main thread for seconds on a 4096 × 2048 map.
 */

import { KDTree3D } from '../../components/map/utils/kdtree'

interface Request {
  ids: Uint32Array
  x: Float64Array
  y: Float64Array
  z: Float64Array
  width: number
  height: number
}

const DEG2RAD = Math.PI / 180

self.onmessage = ({ data }: MessageEvent<Request>) => {
  const { ids, x, y, z, width, height } = data
  const points: Array<[number, number, number, number]> = new Array(ids.length)
  for (let i = 0; i < ids.length; i++) points[i] = [x[i], y[i], z[i], ids[i]]
  const tree = new KDTree3D(points, true)
  const map = new Uint32Array(width * height)

  const cosLon = new Float64Array(width)
  const sinLon = new Float64Array(width)
  for (let px = 0; px < width; px++) {
    const lonRad = ((px / (width - 1)) * 360 - 180) * DEG2RAD
    cosLon[px] = Math.cos(lonRad)
    sinLon[px] = Math.sin(lonRad)
  }

  for (let py = 0; py < height; py++) {
    const latRad = (90 - (py / (height - 1)) * 180) * DEG2RAD
    const cosLat = Math.cos(latRad)
    const sinLat = Math.sin(latRad)
    const rowOff = py * width
    for (let px = 0; px < width; px++) {
      map[rowOff + px] = tree.nearest(cosLat * cosLon[px], sinLat, cosLat * sinLon[px])
    }
  }
  const workerScope = self as unknown as Worker
  workerScope.postMessage({ map }, [map.buffer])
}
