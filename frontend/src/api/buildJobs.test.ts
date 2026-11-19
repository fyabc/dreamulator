import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../i18n', () => ({ default: { language: 'en' } }))

import { api } from './client'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('build job client', () => {
  it('reads the build grid for the selected branch without starting a job', async () => {
    vi.stubEnv('VITE_STATIC_MODE', 'false')
    const grid = { num_cells: 3072, reuses_mesh: false }
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => grid })
    vi.stubGlobal('fetch', fetch)
    await expect(api.getBuildGrid('my world', 'test branch')).resolves.toEqual(grid)
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/worlds/my%20world/build-grid?branch=test%20branch')
    expect(init.method).toBeUndefined()
    expect(init.cache).toBe('no-store')
  })

  it('passes branch, engine and force through the background API', async () => {
    vi.stubEnv('VITE_STATIC_MODE', 'false')
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: 'job' }) })
    vi.stubGlobal('fetch', fetch)
    await api.startBuildJob('my world', { branch: 'climate-dev', engine: 'climate', force: true })
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/worlds/my%20world/build-jobs')
    expect(JSON.parse(init.body)).toEqual({ branch: 'climate-dev', engine: 'climate', force: true })
    await api.getBuildJob('my world', 'job')
    expect(fetch.mock.calls[1][0]).toBe('/api/worlds/my%20world/build-jobs/job')
  })

  it('preserves the synchronous client while adding branch and force', async () => {
    vi.stubEnv('VITE_STATIC_MODE', 'false')
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: 'success' }) })
    vi.stubGlobal('fetch', fetch)
    await api.buildWorld('sample', 'climate', { branch: 'test', force: true })
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({
      branch: 'test', force: true, engine: 'climate',
    })
  })

  it('rejects build operations in static mode before any network request', async () => {
    vi.stubEnv('VITE_STATIC_MODE', 'true')
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    await expect(api.getBuildGrid('sample')).rejects.toThrow('not available in static mode')
    await expect(api.startBuildJob('sample')).rejects.toThrow('not available in static mode')
    await expect(api.getBuildJob('sample', 'job')).rejects.toThrow('not available in static mode')
    expect(fetch).not.toHaveBeenCalled()
  })
})
