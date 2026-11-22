import { decodeWorldTerrainSource, prepareWorldTerrainSource, readNativeTerrain } from '../viewers/packs/worldTerrainSource'
import type { PackWindow } from '../viewers/packs/packCoords'

export type WorldTerrainRequest = { bytes: ArrayBuffer; native: Blob | null; window: PackWindow }
self.onmessage = async ({ data }: MessageEvent<WorldTerrainRequest>) => {
  try {
    const source = decodeWorldTerrainSource(data.bytes)
    if (!source) throw new Error('Missing world TD source')
    self.postMessage({ grid: prepareWorldTerrainSource(source, data.window, data.native ? await readNativeTerrain(data.native) : null) })
  } catch (error) {
    self.postMessage({ error: error instanceof Error ? error.message : String(error) })
  }
}
