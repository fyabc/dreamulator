import { encode } from '@msgpack/msgpack'
import { describe, expect, it } from 'vitest'
import { koppenProductFor, observedKoppenPixels, readObservedKoppen } from './observedKoppen'
import { KOPPEN_COLORS } from './utils/colorScales'

describe('observed Köppen', () => {
  it('preserves legacy Earth observations but treats an EBM result as model data', () => {
    const observed = { source: 'observed', raster: true } as const
    const model = { source: 'model', same_grid_monthly: false } as const
    expect(koppenProductFor(undefined, true, false)).toEqual({ source: 'observed', raster: false })
    expect(koppenProductFor(observed, false, false)).toEqual(observed)
    expect(koppenProductFor(model, true, false)).toEqual(model)
    expect(koppenProductFor(observed, true, true)).toEqual({ source: 'model', same_grid_monthly: true })
  })

  it('uses exact categorical colors, preserving longitude and putting the south in the first texture row', () => {
    const pixels = observedKoppenPixels({
      width: 2, height: 2, classes: ['N/A', 'Af', 'ET', 'Cfa'], pixels: Uint8Array.of(1, 2, 0, 3),
    })
    const actualColors = [0, 4, 8, 12].map(start =>
      '#' + [...pixels.subarray(start, start + 3)].map(channel => channel.toString(16).padStart(2, '0')).join(''),
    )
    expect(actualColors).toEqual(['Ocean', 'Cfa', 'Af', 'ET'].map(code => KOPPEN_COLORS[code].toLowerCase()))
    expect([pixels[3], pixels[7], pixels[11], pixels[15]]).toEqual([255, 255, 255, 255])
  })

  it('rejects invalid raster packets instead of displaying incorrect coordinates', async () => {
    const data = new Blob([new Uint8Array(encode({ version: 1, width: 1, height: 1 }))])
    const gzip = await new Response(data.stream().pipeThrough(new CompressionStream('gzip'))).blob()
    await expect(readObservedKoppen(gzip)).rejects.toThrow('Invalid observed Köppen raster')
  })
})
