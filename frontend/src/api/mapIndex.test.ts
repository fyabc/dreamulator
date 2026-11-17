import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../i18n', () => ({ default: { language: 'en' } }))

import { api } from './client'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

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
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls[0][0]).toBe(mode === 'true'
      ? '/data/worlds/probe/branches/climate-dev/maps/maps.json'
      : '/api/worlds/probe/maps?branch=climate-dev')
  })
})
