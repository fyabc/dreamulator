import { decodeWorldTerrainSource, prepareWorldTerrainSource, readNativeTerrain } from '../viewers/packs/worldTerrainSource'
import type { PackWindow } from '../viewers/packs/packCoords'
import { readElevationPng } from '../viewers/packs/elevationRaster'
import { sha256 } from '../projects/creationSnapshot'

export type WorldTerrainRequest = { bytes: ArrayBuffer; native: Blob | null; window: PackWindow;
  png?: { blob: Blob; min: number; max: number } }
self.onmessage = async ({ data }: MessageEvent<WorldTerrainRequest>) => {
  try {
    const source = decodeWorldTerrainSource(data.bytes)
    if (!source) throw new Error('Missing world TD source')
    const { png } = data
    if (png && await sha256(png.blob) !== source.native) throw new Error('Climate result elevation checksum mismatch')
    const native = png ? await readElevationPng(png.blob, png.min, png.max)
      : data.native ? await readNativeTerrain(data.native) : null
    self.postMessage({ grid: prepareWorldTerrainSource(source, data.window, native) })
  } catch (error) {
    self.postMessage({ error: error instanceof Error ? error.message : String(error) })
  }
}
