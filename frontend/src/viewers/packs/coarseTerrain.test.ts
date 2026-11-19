import { describe, expect, it } from 'vitest'
import { stitchCoarseElevation } from './coarseTerrain'

describe('coarse terrain stitching', () => {
  it('blends in the signed square-root domain before decoding elevation to metres', () => {
    const left = new Float32Array(64 * 64).fill(-4)
    const right = new Float32Array(64 * 64).fill(2)
    const weights = new Float32Array(left.length).fill(1)
    const { width, height, values } = stitchCoarseElevation([left, right], weights)
    expect([width, height]).toEqual([112, 64])
    expect([values[47], values[48], values[63], values[64], values[111]]).toEqual([-16, -1, -1, 4, 4])
  })

  it('rejects non-finite results instead of drawing them as valid terrain', () => {
    const tile = new Float32Array(64 * 64).fill(NaN)
    expect(() => stitchCoarseElevation([tile], tile)).toThrow(/invalid elevations/)
  })
})
