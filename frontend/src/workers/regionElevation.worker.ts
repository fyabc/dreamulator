import { elevationPng, elevationTiff, readElevationNpy, readElevationPng, resizeElevation, sampleGlobalElevation,
  type ElevationFormat, type ElevationRaster } from '../viewers/packs/elevationRaster'
import type { PackWindow } from '../viewers/packs/packCoords'

export type ElevationWorkerRequest =
  | { kind: 'global'; blob: Blob; min: number; max: number; window: PackWindow }
  | { kind: 'project-png'; blob: Blob; min: number; max: number; maxSide: number }
  | { kind: 'project-raster'; raster: ElevationRaster }
  | { kind: 'pack'; blob: Blob }
  | { kind: 'export'; size: number | null; format: ElevationFormat; metadata: Record<string, unknown>; raster?: ElevationRaster }

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
    } else if (data.kind === 'project-png') {
      const view = new DataView(await data.blob.slice(0, 24).arrayBuffer())
      const width = view.getUint32(16)
      if (!width || width > data.maxSide || width !== view.getUint32(20)) throw new Error('Invalid source dimensions')
      const raster = await readElevationPng(data.blob, data.min, data.max)
      self.postMessage({ kind: 'preview', raster, sourceWidth: raster.width, sourceHeight: raster.height } satisfies ElevationWorkerResult,
        { transfer: [raster.values.buffer] })
    } else if (data.kind === 'project-raster') {
      source = data.raster
      window = undefined
      self.postMessage({ kind: 'ready', width: source.width, height: source.height } satisfies ElevationWorkerResult)
    } else if (data.kind === 'pack') {
      source = readElevationNpy(await data.blob.arrayBuffer())
      window = undefined
      self.postMessage({ kind: 'ready', width: source.width, height: source.height } satisfies ElevationWorkerResult)
    } else {
      const { size } = data
      const input = data.raster ?? source
      if (!input) throw new Error('Missing elevation export source')
      const longest = Math.max(input.width, input.height)
      const raster = data.raster ?? (size === null ? input : window ? sampleGlobalElevation(input, window, size)
        : resizeElevation(input, Math.max(1, Math.round(size * input.width / longest)),
          Math.max(1, Math.round(size * input.height / longest))))
      const blob = data.format === 'png' ? await elevationPng(raster, data.metadata) : elevationTiff(raster, data.metadata)
      self.postMessage({ kind: 'file', blob } satisfies ElevationWorkerResult)
    }
  } catch {
    self.postMessage({ kind: 'error' } satisfies ElevationWorkerResult)
  }
}
