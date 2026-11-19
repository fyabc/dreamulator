import { encode } from '@msgpack/msgpack'
import { describe, expect, it } from 'vitest'
import { decodeMonthlyClimate } from './monthlyClimate'

function decodeFixture(time: Record<string, unknown>) {
  const packed = encode({
    num_cells: 1,
    months: 12,
    t_monthly: new Uint8Array(new Float32Array(12).fill(11).buffer),
    p_monthly: new Uint8Array(new Float32Array(12).fill(20).buffer),
    ...time,
  })
  return decodeMonthlyClimate(new Uint8Array(packed).buffer)
}

describe('decodeMonthlyClimate time declaration', () => {
  it('preserves the first window, duration and amount without rescaling', () => {
    const data = decodeFixture({ month_0: 'ls_15_first_bin_center', bin_days: 57.25, window_days: 687 })
    expect(data.month0).toBe('ls_15_first_bin_center')
    expect(data.binDays).toBe(57.25)
    expect(data.windowDays).toBe(687)
    expect(data.pMonthly[0]).toBe(20)
  })

  it('leaves undeclared calendar fields missing', () => {
    const data = decodeFixture({})
    expect(data.month0).toBeUndefined()
    expect(data.binDays).toBeUndefined()
    expect(data.windowDays).toBeUndefined()
  })
})
