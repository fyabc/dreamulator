import { describe, expect, it, vi } from 'vitest'
import { detectWebGpu } from './webGpuDevice'

describe('regional compute device', () => {
  it('shows the hardware name and selects the browser’s high-performance adapter', async () => {
    const adapter = { info: { description: 'NVIDIA L20', isFallbackAdapter: false } }
    const requestAdapter = vi.fn().mockResolvedValue(adapter)
    await expect(detectWebGpu({ requestAdapter })).resolves.toEqual({ adapter, kind: 'hardware', name: 'NVIDIA L20' })
    expect(requestAdapter).toHaveBeenCalledWith({ powerPreference: 'high-performance' })
  })

  it('uses the vendor and architecture without inventing a model or a hardware claim', async () => {
    await expect(detectWebGpu({ requestAdapter: async () => ({ info: { vendor: 'nvidia', architecture: 'lovelace' } }) }))
      .resolves.toMatchObject({ kind: 'unknown', name: 'NVIDIA lovelace' })
  })

  it('reports software separately and tolerates failed device detection', async () => {
    await expect(detectWebGpu({ requestAdapter: async () => ({ info: { isFallbackAdapter: true } }) }))
      .resolves.toMatchObject({ kind: 'software', name: null })
    await expect(detectWebGpu({ requestAdapter: async () => null })).resolves.toBeNull()
    await expect(detectWebGpu({ requestAdapter: vi.fn().mockRejectedValue(new Error('blocked')) })).resolves.toBeNull()
  })
})
