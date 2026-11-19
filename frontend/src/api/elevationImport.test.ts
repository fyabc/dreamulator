import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../i18n', () => ({ default: { language: 'en' } }))

import { api } from './client'
import {
  decodePreviewGrid,
  mappingFormFields,
  pixelLatLon,
  suggestWorldName,
  type ElevationMapping,
} from './elevationImport'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

const THRESHOLD: ElevationMapping = {
  mode: 'threshold',
  min_m: -11000,
  max_m: 6000,
  sea_level: 0.05,
  sea_level_m: 0,
  curve: 'linear',
  gamma: 1,
  seafloor_m: -3000,
}

function b64(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
}

describe('elevation import helpers', () => {
  it('decodes the little-endian preview grid', () => {
    const metres = new Float32Array([-3000, 0.5, 1234.25, 6000])
    const le = new Uint8Array(16)
    const view = new DataView(le.buffer)
    metres.forEach((m, i) => view.setFloat32(i * 4, m, true))
    const grid = decodePreviewGrid({ width: 2, height: 2, metres_f32: b64(le), land_u8: b64(new Uint8Array([0, 1, 1, 1])) })
    expect(Array.from(grid.metres)).toEqual([-3000, 0.5, 1234.25, 6000])
    expect(Array.from(grid.land)).toEqual([0, 1, 1, 1])
    expect(() => decodePreviewGrid({ width: 3, height: 2, metres_f32: b64(le), land_u8: b64(new Uint8Array(4)) })).toThrow()
  })

  it('sends only the fields the chosen mode reads', () => {
    expect(mappingFormFields(null)).toEqual({})
    expect(mappingFormFields(THRESHOLD)).toEqual({
      mode: 'threshold',
      sea_level: '0.05',
      max_m: '6000',
      curve: 'linear',
      gamma: '1',
      seafloor_m: '-3000',
    })
    expect(mappingFormFields({ ...THRESHOLD, mode: 'metres', sea_level_m: 12 })).toEqual({ mode: 'metres', sea_level_m: '12' })
  })

  it('places pixel centres on the equirectangular grid', () => {
    expect(pixelLatLon(0, 0, 4, 2)).toEqual([45, -135])
    expect(pixelLatLon(3, 1, 4, 2)).toEqual([-45, 135])
  })

  it('suggests a safe world name that is not taken', () => {
    expect(suggestWorldName('My Map (v2).png')).toBe('My-Map-v2')
    expect(suggestWorldName('地图.tif')).toBe('my-world')
    expect(suggestWorldName('sample.png', ['sample', 'sample-2'])).toBe('sample-3')
  })
})

describe('elevation import client', () => {
  it('previews with the target in the query and the mapping in the form', async () => {
    vi.stubEnv('VITE_STATIC_MODE', 'false')
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) })
    vi.stubGlobal('fetch', fetch)
    const file = new File([new Uint8Array([1, 2, 3])], 'map.png')
    await api.previewElevationImport(file, THRESHOLD, { world: 'my world', planetId: 'planet_gaia', branch: 'geo' })
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/elevation-preview?world=my+world&planet_id=planet_gaia&branch=geo')
    expect(init.method).toBe('POST')
    const form = init.body as FormData
    expect(form.get('mode')).toBe('threshold')
    expect(form.get('seafloor_m')).toBe('-3000')
    expect(form.get('min_m')).toBeNull()
    expect(form.get('file')).toBeInstanceOf(File)
  })

  it('previews a new world without a target', async () => {
    vi.stubEnv('VITE_STATIC_MODE', 'false')
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true }) })
    vi.stubGlobal('fetch', fetch)
    await api.previewElevationImport(new File([], 'm.png'), null)
    expect(fetch.mock.calls[0][0]).toBe('/api/elevation-preview')
    expect(Array.from((fetch.mock.calls[0][1].body as FormData).keys())).toEqual(['file'])
  })

  it('throws the backend detail when an import is rejected', async () => {
    vi.stubEnv('VITE_STATIC_MODE', 'false')
    const fetch = vi.fn().mockResolvedValue({ ok: false, status: 400, json: async () => ({ detail: 'bad image' }) })
    vi.stubGlobal('fetch', fetch)
    await expect(api.importElevation('w', 'p', new File([], 'm.png'), null, THRESHOLD, 'note')).rejects.toThrow('bad image')
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/worlds/w/maps/p/import-elevation')
    expect((init.body as FormData).get('notes')).toBe('note')
  })

  it('refuses previews and imports in static mode', async () => {
    vi.stubEnv('VITE_STATIC_MODE', 'true')
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    await expect(api.previewElevationImport(new File([], 'm.png'), null)).rejects.toThrow()
    await expect(api.importElevation('w', 'p', new File([], 'm.png'))).rejects.toThrow()
    expect(fetch).not.toHaveBeenCalled()
  })
})
