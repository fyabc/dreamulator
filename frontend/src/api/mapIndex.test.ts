import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../i18n', () => ({ default: { language: 'en' } }))

import { api } from './client'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

function stubFetch(shared: string[], planets: string[]) {
  const fetch = vi.fn(async (url: string) => ({
    ok: true,
    json: async () => (String(url).endsWith('/maps/shared.json') ? shared : planets),
  }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function urls(fetch: ReturnType<typeof vi.fn>): string[] {
  return fetch.mock.calls.map(([url]) => String(url))
}

describe('map index transport', () => {
  it.each(['false', 'true'])('keeps branch-first inherited maps in static mode %s', async (mode) => {
    vi.stubEnv('VITE_STATIC_MODE', mode)
    const planets = ['z_overlaid', 'a_inherited']
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mode === 'true' ? planets : { ok: true, data: planets },
    })
    vi.stubGlobal('fetch', fetch)

    expect(await api.listMapPlanets('probe', 'climate-dev')).toEqual(planets)
    const calls = urls(fetch)
    if (mode === 'true') {
      // The shared-file manifest is consulted before the branch index.
      expect(calls).toEqual([
        '/data/worlds/probe/branches/climate-dev/maps/shared.json',
        '/data/worlds/probe/branches/climate-dev/maps/maps.json',
      ])
    } else {
      expect(calls).toEqual(['/api/worlds/probe/maps?branch=climate-dev'])
    }
  })

  it('reads the root index when the branch manifest marks it shared', async () => {
    vi.stubEnv('VITE_STATIC_MODE', 'true')
    const planets = ['z_overlaid', 'a_inherited']
    const fetch = stubFetch(['maps.json'], planets)

    expect(await api.listMapPlanets('probe-shared', 'climate-dev')).toEqual(planets)
    expect(urls(fetch)).toEqual([
      '/data/worlds/probe-shared/branches/climate-dev/maps/shared.json',
      '/data/worlds/probe-shared/maps/maps.json',
    ])
  })
})
