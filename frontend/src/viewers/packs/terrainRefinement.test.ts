import { afterEach, describe, expect, it, vi } from 'vitest'
import { checkedAsset, coarseCondition } from './terrainRefinement'
import { prepareTerrainConditions } from './terrainConditions'
import { coveringTiles, makeTerrainPlan, square, stitchTiles, terrainNoise } from './terrainTiles'

describe('browser terrain model loading', () => {
  const base = new URL('https://example.test/models/')
  const name = 'decoder.onnx'
  const model = Uint8Array.of(1, 2, 3, 4)
  const hash = '9f64a747e1b97f131fabb6b447296c9b6f0201e79fb3c5356e6c77e89b6a806a'

  afterEach(() => vi.unstubAllGlobals())

  it('reports chunks before verifying and uses the manifest size without a Content-Length header', async () => {
    let stream!: ReadableStreamDefaultController<Uint8Array>
    const body = new ReadableStream<Uint8Array>({ start: (controller) => { stream = controller } })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body)))
    const updates: (number | string)[] = []
    const result = checkedAsset(base, name, hash, new AbortController().signal, {
      bytes: model.length,
      reading: (received) => updates.push(received),
      verifying: async () => { updates.push('verify') },
    })
    stream.enqueue(model.subarray(0, 2))
    await vi.waitFor(() => expect(updates).toEqual([0, 2]))
    stream.enqueue(model.subarray(2))
    stream.close()
    expect(new Uint8Array((await result).data)).toEqual(model)
    expect(updates).toEqual([0, 2, 4, 'verify'])
  })

  it.each([3, 5])('rejects models that do not match the manifest size %i before hashing', async (bytes) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(model)))
    const verifying = vi.fn()
    await expect(checkedAsset(base, name, hash, new AbortController().signal, { bytes, reading: vi.fn(), verifying }))
      .rejects.toThrow('unexpected size')
    expect(verifying).not.toHaveBeenCalled()
  })

  it('reports the verification phase before rejecting an invalid digest', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(model)))
    const verifying = vi.fn()
    await expect(checkedAsset(base, name, '0'.repeat(64), new AbortController().signal, {
      bytes: model.length, reading: vi.fn(), verifying,
    })).rejects.toThrow('SHA-256 mismatch')
    expect(verifying).toHaveBeenCalledOnce()
  })

  it('cancels the stream without verifying a partially read model', async () => {
    const controller = new AbortController()
    const cancelled = vi.fn()
    const body = new ReadableStream<Uint8Array>({
      start: (stream) => { stream.enqueue(model.subarray(0, 2)); stream.enqueue(model.subarray(2)) },
      cancel: cancelled,
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body)))
    const verifying = vi.fn()
    await expect(checkedAsset(base, name, hash, controller.signal, {
      bytes: model.length, reading: (received) => { if (received) controller.abort() }, verifying,
    })).rejects.toThrow(/aborted/)
    expect(cancelled).toHaveBeenCalledOnce()
    expect(verifying).not.toHaveBeenCalled()
  })

  it('reads the verified model from storage without fetching it and reports the source', async () => {
    const fetchModel = vi.fn()
    vi.stubGlobal('fetch', fetchModel)
    const getFileHandle = vi.fn().mockResolvedValue({ getFile: async () => new Blob([model]) })
    const storage = { getFileHandle } as unknown as FileSystemDirectoryHandle
    const reading = vi.fn()
    const result = await checkedAsset(base, name, hash, new AbortController().signal,
      { bytes: model.length, reading, verifying: vi.fn() }, storage)
    expect(result.reusable).toBe(true)
    expect(reading).toHaveBeenLastCalledWith(model.length, 'cache')
    expect(getFileHandle).toHaveBeenCalledWith(`${name}.${hash}`)
    expect(fetchModel).not.toHaveBeenCalled()
  })

  it('replaces a corrupt cached model only after the replacement passes verification', async () => {
    const writer = { write: vi.fn(), close: vi.fn() }
    const getFileHandle = vi.fn().mockResolvedValueOnce({ getFile: async () => new Blob([model.slice().reverse()]) })
      .mockResolvedValueOnce({ createWritable: async () => writer })
    const removeEntry = vi.fn().mockResolvedValue(undefined)
    const storage = { getFileHandle, removeEntry } as unknown as FileSystemDirectoryHandle
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(model)))
    const result = await checkedAsset(base, name, hash, new AbortController().signal,
      { bytes: model.length, reading: vi.fn(), verifying: vi.fn() }, storage)
    expect(removeEntry).toHaveBeenCalledWith(`${name}.${hash}`)
    expect(writer.write).toHaveBeenCalledWith(model)
    expect(writer.close).toHaveBeenCalledOnce()
    expect(result.reusable).toBe(true)
  })

  it('still returns the verified model when its cache write exceeds quota', async () => {
    const writer = { write: vi.fn().mockRejectedValue(new DOMException('', 'QuotaExceededError')), abort: vi.fn().mockResolvedValue(undefined) }
    const getFileHandle = vi.fn().mockRejectedValueOnce(new DOMException('', 'NotFoundError'))
      .mockResolvedValueOnce({ createWritable: async () => writer })
    const storage = { getFileHandle } as unknown as FileSystemDirectoryHandle
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(model)))
    const result = await checkedAsset(base, name, hash, new AbortController().signal,
      { bytes: model.length, reading: vi.fn(), verifying: vi.fn() }, storage)
    expect(writer.abort).toHaveBeenCalledOnce()
    expect(new Uint8Array(result.data)).toEqual(model)
    expect(result.reusable).toBe(false)
  })
})

describe('browser terrain refinement inputs', () => {
  it('shares the same input grid, output size and tile counts between the budget and the runner', () => {
    for (const span of [NaN, Infinity, 0, 20, 500]) expect(() => makeTerrainPlan(span)).toThrow(/out of range/)
    const plan = makeTerrainPlan(46)
    expect(plan).toMatchObject({ inputSize: 2, size: 512, totals: { coarse: 4, base: 100, decoder: 9 } })
    expect(makeTerrainPlan(184)).toMatchObject({ inputSize: 8, size: 2048 })
    expect(makeTerrainPlan(103.5).inputSize).toBe(4)
    expect(plan.padded.right - plan.padded.left).toBe(512 + 96)
    expect(plan.low.right - plan.low.left).toBe((512 + 96) / 8)
    expect(plan.initial.length).toBeGreaterThan(plan.final.length)
  })

  it('uses the selected elevation in metres relative to sea level, without changing climate placeholders', () => {
    const settings = { means: [0, 0, 0, 0, 0, 0], stds: [1, 1, 1, 1, 1, 1], snr: [0, 0, 0, 0, 0] }
    const tile = { row: 1, col: 1 }
    const raster = prepareTerrainConditions({ width: 2, height: 2, values: Float32Array.of(-15, 5, 21, 30) }, 46)
    const conditioned = coarseCondition(raster, tile, 5, settings)
    expect([conditioned[16 * 64 + 17], conditioned[17 * 64 + 16], conditioned[17 * 64 + 17]]).toEqual([0, 4, 5])
    const raised = coarseCondition(raster, tile, 21, settings)
    expect(raised[17 * 64 + 16]).toBe(0)
    expect(raised.subarray(64 * 64)).toEqual(conditioned.subarray(64 * 64))
    const reseeded = coarseCondition(raster, tile, 5, { ...settings, snr: [0, 1, 1, 1, 1] }, 8)
    expect(reseeded.subarray(0, 64 * 64)).toEqual(conditioned.subarray(0, 64 * 64))
    expect(reseeded).not.toEqual(coarseCondition(raster, tile, 5, { ...settings, snr: [0, 1, 1, 1, 1] }))
  })

  it('normalizes all five recorded TD channels in model order, including the padded cells', () => {
    const grid = prepareTerrainConditions({ width: 2, height: 2, values: Float32Array.of(-4, 9, 16, 25) }, 46, {
      temperature_mean_c: Float32Array.of(10, 20, 30, 40),
      temperature_std_c: Float32Array.of(1, 2, 3, 4),
      precipitation_total_mm: Float32Array.of(100, 200, 300, 400),
      precipitation_cv_pct: Float32Array.of(11, 12, 13, 14),
    })
    const settings = { means: [0, 1000, 10, 100, 100, 10], stds: [1, 1, 2, 10, 100, 2], snr: [0, 0, 0, 0, 0] }
    const condition = coarseCondition(grid, { row: 1, col: 1 }, 100, settings)
    const pixel = (row: number, col: number) => Array.from({ length: 5 }, (_, channel) => condition[(channel * 64 + row) * 64 + col])
    expect(pixel(0, 0)).toEqual([-2, 0, 0, 0, 0.5])
    expect(pixel(63, 63)).toEqual([5, Math.fround((Math.fround(40 + 5.9 * .025) - 10) / 2), 30, 3, 2])
    expect(pixel(16, 17)[2]).toBe(10)
    expect(pixel(17, 16)[2]).toBe(20)
  })

  it('uses one noise field and blends neighbouring tiles in their overlap', () => {
    const original = terrainNoise(42, 0, 0, 4, 2)
    const moved = terrainNoise(42, 1, 1, 4, 2)
    expect(moved[0]).toBe(original[5])
    expect(moved[16 + 4]).toBe(original[16 + 9])
    expect(terrainNoise(43, 0, 0, 4, 2)).not.toEqual(original)
    const area = square(0, 0, 1)
    expect(coveringTiles(area, 4, 2)).toHaveLength(4)
    const tiles = new Map(coveringTiles(area, 4, 2).map(({ row, col }) => [`${row},${col}`, new Float32Array(16).fill(42)]))
    expect(stitchTiles(tiles, area, 4, 2, 1)[0]).toBeCloseTo(42, 4)
    tiles.clear()
    expect(() => stitchTiles(tiles, area, 4, 2, 1)).toThrow(/Missing/)
  })
})
