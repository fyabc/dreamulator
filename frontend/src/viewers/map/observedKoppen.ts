import { decode } from '@msgpack/msgpack'
import type { KoppenProduct } from './types'
import { KOPPEN_COLORS } from './utils/colorScales'

export function koppenProductFor(product: KoppenProduct | undefined, legacyObservation: boolean, experiment: boolean): KoppenProduct {
  if (experiment) return { source: 'model', same_grid_monthly: true }
  return product ?? (legacyObservation ? { source: 'observed', raster: false } : { source: 'model', same_grid_monthly: true })
}

export interface ObservedKoppenRaster {
  width: number
  height: number
  classes: string[]
  pixels: Uint8Array
}

export async function readObservedKoppen(blob: Blob): Promise<ObservedKoppenRaster> {
  const raw = await new Response(blob.stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer()
  const packet = decode(raw) as Partial<ObservedKoppenRaster & { version: number }> | null
  if (!packet || packet.version !== 1 || packet.width !== 4320 || packet.height !== 2160 ||
      !Array.isArray(packet.classes) || packet.classes.length !== 31 || packet.classes[0] !== 'N/A' ||
      !packet.classes.slice(1).every(code => typeof code === 'string' && Object.prototype.hasOwnProperty.call(KOPPEN_COLORS, code)) ||
      !(packet.pixels instanceof Uint8Array) || packet.pixels.length !== packet.width * packet.height) {
    throw new Error('Invalid observed Köppen raster')
  }
  return { width: packet.width, height: packet.height, classes: packet.classes, pixels: packet.pixels }
}

export function observedKoppenPixels({ width, height, classes, pixels }: ObservedKoppenRaster): Uint8Array {
  const noData = Number.parseInt(KOPPEN_COLORS.Ocean.slice(1), 16)
  const palette = classes.map(code => KOPPEN_COLORS[code] ? Number.parseInt(KOPPEN_COLORS[code].slice(1), 16) : noData)
  const rgba = new Uint8Array(width * height * 4)
  for (let row = 0; row < height; row++) {
    const src = row * width
    const dst = (height - 1 - row) * width * 4
    for (let column = 0; column < width; column++) {
      const color = palette[pixels[src + column]] ?? noData
      const index = dst + column * 4
      rgba[index] = color >> 16
      rgba[index + 1] = color >> 8
      rgba[index + 2] = color
      rgba[index + 3] = 255
    }
  }
  return rgba
}
