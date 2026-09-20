/**
 * yearlyClimate decoder tests — classification fields (UCC-01 step 4a) are
 * optional: exports that predate them must still decode, with the
 * classification fields absent (the layer then degrades to transparent).
 */

import { describe, expect, it } from 'vitest'
import { encode } from '@msgpack/msgpack'
import { decodeYearlyClimate } from './yearlyClimate'

/** encode() views a pooled 2048-byte buffer — slice to the exact bytes. */
function toBuffer(payload: Record<string, unknown>): ArrayBuffer {
  const u8 = encode(payload)
  return u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength) as ArrayBuffer
}

function basePayload(): Record<string, unknown> {
  const f32 = (v: number[]) => new Uint8Array(new Float32Array(v).buffer)
  const u8 = (v: number[]) => new Uint8Array(v)
  return {
    format_version: 'test',
    num_cells: 2,
    months: 12,
    demand_model: 'hamon-1961',
    freeze_threshold_c: 0,
    status_codes: ['valid', 'missing_input', 'not_applicable', 'no_positive_demand'],
    t_mean_c: f32([10, 20]),
    t_min_c: f32([5, 15]),
    t_max_c: f32([15, 25]),
    t_range_c: f32([10, 10]),
    t_below_frac: f32([0, 0]),
    p_mean_mm_per_month: f32([50, 60]),
    p_total_mm: f32([600, 720]),
    ai: f32([0.5, 1.2]),
    ai_status: u8([0, 0]),
    deficit: f32([0.1, 0.0]),
    deficit_status: u8([0, 0]),
    concentration: f32([0.3, 0.1]),
  }
}

describe('decodeYearlyClimate', () => {
  it('decodes classification fields when present', () => {
    const payload = {
      ...basePayload(),
      profile: 'ucc-v0',
      thermal_bands: ['polar', 'cold', 'temperate', 'tropical'],
      supply_bands: ['arid', 'transitional', 'humid'],
      ucc_thermal: new Uint8Array([2, 3]),
      ucc_supply: new Uint8Array([0, 255]),
      ucc_supply_status: new Uint8Array([0, 2]),
      ucc_modifiers: new Uint8Array([3, 0]),
    }
    const d = decodeYearlyClimate(toBuffer(payload))
    expect(d.profile).toBe('ucc-v0')
    expect(d.thermalBands).toEqual(['polar', 'cold', 'temperate', 'tropical'])
    expect(d.supplyBands).toEqual(['arid', 'transitional', 'humid'])
    expect([...d.uccThermal!]).toEqual([2, 3])
    expect([...d.uccSupply!]).toEqual([0, 255])
    expect([...d.uccSupplyStatus!]).toEqual([0, 2])
    expect([...d.uccModifiers!]).toEqual([3, 0])
    // Descriptors still decode alongside.
    expect(d.tMeanC[1]).toBeCloseTo(20)
    expect(d.ai[0]).toBeCloseTo(0.5)
  })

  it('leaves classification fields undefined on older exports', () => {
    const d = decodeYearlyClimate(toBuffer(basePayload()))
    expect(d.profile).toBeUndefined()
    expect(d.uccThermal).toBeUndefined()
    expect(d.uccSupply).toBeUndefined()
    expect(d.uccSupplyStatus).toBeUndefined()
    expect(d.uccModifiers).toBeUndefined()
    expect(d.tMeanC[0]).toBeCloseTo(10)
  })
})
