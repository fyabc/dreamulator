import { afterEach, describe, expect, it, vi } from 'vitest'
import { clearTerrainModelCache, readTerrainModelCacheBytes } from './terrainModelCache'

const directoryName = 'dreamulator-terrain-models-v1'

function mockStorage() {
  const root = { getDirectoryHandle: vi.fn(), removeEntry: vi.fn() }
  vi.stubGlobal('navigator', { storage: { getDirectory: vi.fn().mockResolvedValue(root) } })
  return root
}

describe('terrain model cache management', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('counts all cached model versions from file sizes without reading their contents', async () => {
    const root = mockStorage()
    root.getDirectoryHandle.mockResolvedValue({
      values: async function* () {
        yield { kind: 'file', name: 'manifest.json.current', getFile: async () => ({ size: 6658 }) }
        yield { kind: 'file', name: 'base.onnx.current', getFile: async () => ({ size: 1015166929 }) }
        yield { kind: 'file', name: 'base.onnx.previous', getFile: async () => ({ size: 990000000 }) }
      },
    })
    expect(await readTerrainModelCacheBytes()).toBe(2005173587)
    expect(root.getDirectoryHandle).toHaveBeenCalledExactlyOnceWith(directoryName)
  })

  it('reports an absent cache as empty without creating a directory', async () => {
    const root = mockStorage()
    root.getDirectoryHandle.mockRejectedValue(new DOMException('', 'NotFoundError'))
    await expect(readTerrainModelCacheBytes()).resolves.toBe(0)
    expect(root.getDirectoryHandle).toHaveBeenCalledExactlyOnceWith(directoryName)
  })

  it('clears only the terrain model directory and tolerates it already being absent', async () => {
    const root = mockStorage()
    root.removeEntry.mockRejectedValue(new DOMException('', 'NotFoundError'))
    await expect(clearTerrainModelCache()).resolves.toBeUndefined()
    expect(root.removeEntry).toHaveBeenCalledExactlyOnceWith(directoryName, { recursive: true })
  })

  it('reports denied cache operations instead of treating them as successful', async () => {
    const root = mockStorage()
    const denied = new DOMException('', 'NotAllowedError')
    root.getDirectoryHandle.mockRejectedValue(denied)
    root.removeEntry.mockRejectedValue(denied)
    await expect(readTerrainModelCacheBytes()).rejects.toBe(denied)
    await expect(clearTerrainModelCache()).rejects.toBe(denied)
  })
})
