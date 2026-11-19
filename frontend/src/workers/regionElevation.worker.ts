import { elevationPng, elevationTiff, readElevationNpy, readElevationPng, resizeElevation, sampleGlobalElevation,
  type ElevationFormat, type ElevationRaster } from '../viewers/packs/elevationRaster'
import type { PackWindow } from '../viewers/packs/packCoords'

export type ElevationWorkerRequest =
  | { kind: 'global'; blob: Blob; min: number; max: number; window: PackWindow }
  | { kind: 'pack'; blob: Blob }
  | { kind: 'export'; size: number | null; format: ElevationFormat; metadata: Record<string, unknown> }

export type ElevationWorkerResult =
  | { kind: 'preview'; raster: ElevationRaster; sourceWidth: number; sourceHeight: number }
  | { kind: 'ready'; width: number; height: number }
  | { kind: 'file'; blob: Blob }
  | { kind: 'error' }

let source: ElevationRaster | undefined
let window: PackWindow | undefined

self.onmessage = async ({ data }: MessageEvent<ElevationWorkerRequest>) => {
  try {
    if (data.kind === 'global') {
      source = await readElevationPng(data.blob, data.min, data.max)
      window = data.window
      const raster = sampleGlobalElevation(source, window, 384)
      const result: ElevationWorkerResult = { kind: 'preview', raster, sourceWidth: source.width, sourceHeight: source.height }
      self.postMessage(result, { transfer: [raster.values.buffer] })
    } else if (data.kind === 'pack') {
      source = readElevationNpy(await data.blob.arrayBuffer())
      window = undefined
      self.postMessage({ kind: 'ready', width: source.width, height: source.height } satisfies ElevationWorkerResult)
    } else if (source) {
      const { size } = data
      const longest = Math.max(source.width, source.height)
      const raster = size === null ? source : window ? sampleGlobalElevation(source, window, size)
        : resizeElevation(source, Math.max(1, Math.round(size * source.width / longest)),
          Math.max(1, Math.round(size * source.height / longest)))
      const blob = data.format === 'png' ? await elevationPng(raster, data.metadata) : elevationTiff(raster, data.metadata)
      self.postMessage({ kind: 'file', blob } satisfies ElevationWorkerResult)
    }
  } catch {
    self.postMessage({ kind: 'error' } satisfies ElevationWorkerResult)
  }
}
