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

export function observedKoppenPixels({ width, height, classes, pixels }: ObservedKoppenRaster,
  maxWidth = width): Uint8Array {
  const noData = Number.parseInt(KOPPEN_COLORS.Ocean.slice(1), 16)
  const palette = classes.map(code => KOPPEN_COLORS[code] ? Number.parseInt(KOPPEN_COLORS[code].slice(1), 16) : noData)
  // Phones cap the raster width (2048): an uncapped 4320×2160 texture can exceed
  // the device's max texture size and leave the map canvas black.
  const scale = Math.min(1, maxWidth > 0 ? maxWidth / width : 1)
  const outWidth = Math.max(1, Math.round(width * scale))
  const outHeight = Math.max(1, Math.round(height * scale))
  const rgba = new Uint8Array(outWidth * outHeight * 4)
  for (let row = 0; row < outHeight; row++) {
    const sourceRow = Math.min(height - 1, Math.floor((row + 0.5) * height / outHeight))
    const src = sourceRow * width
    const dst = (outHeight - 1 - row) * outWidth * 4
    for (let column = 0; column < outWidth; column++) {
      const sourceColumn = Math.min(width - 1, Math.floor((column + 0.5) * width / outWidth))
      const color = palette[pixels[src + sourceColumn]] ?? noData
      const index = dst + column * 4
      rgba[index] = color >> 16
      rgba[index + 1] = color >> 8
      rgba[index + 2] = color
      rgba[index + 3] = 255
    }
  }
  return rgba
}
