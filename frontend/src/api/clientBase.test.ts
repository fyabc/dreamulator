import { afterEach, expect, it, vi } from 'vitest'

vi.mock('../i18n', () => ({ default: { language: 'en' } }))

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

it('uses the deployment prefix for API reads, uploads and image URLs', async () => {
  vi.stubEnv('BASE_URL', '/preview/8039/')
  vi.stubEnv('VITE_STATIC_MODE', 'false')
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ['earth'] })
  vi.stubGlobal('fetch', fetch)
  const { api, packImageUrl } = await import('./client')

  await expect(api.listWorlds()).resolves.toEqual(['earth'])
  await api.saveElevation('earth', 'planet_earth', new Blob(), 'test')
  await api.uploadGeographyRaster('earth', new File([], 'raster.png'))

  expect(fetch.mock.calls.map(([url]) => url)).toEqual([
    '/preview/8039/api/worlds',
    '/preview/8039/api/worlds/earth/maps/planet_earth/elevation?branch=test',
    '/preview/8039/api/worlds/earth/geography-raster',
  ])
  expect(packImageUrl('sample', 'source.png')).toBe('/preview/8039/api/packs/sample/image/source.png')
})
