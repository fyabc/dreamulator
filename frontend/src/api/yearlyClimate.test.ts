/**
 * yearlyClimate decoder tests — classification fields (UCC-01 step 4a) are
 * optional: exports that predate them must still decode, with the
 * classification fields absent (the layer then degrades to transparent).
 */

import { describe, expect, it } from 'vitest'
import { encode } from '@msgpack/msgpack'
import { decodeYearlyClimate, uccCode } from './yearlyClimate'

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
    expect(uccCode(d, 0, true)).toBeNull()
  })

  it('composes short codes (mirror of ucc.py)', () => {
    const payload = {
      ...basePayload(),
      profile: 'ucc-v1',
      thermal_bands: ['polar', 'cold', 'temperate', 'tropical'],
      supply_bands: ['arid', 'semi_arid', 'transitional', 'humid'],
      ucc_thermal: new Uint8Array([2, 3]),
      ucc_supply: new Uint8Array([1, 255]),
      ucc_supply_status: new Uint8Array([0, 2]),
      ucc_modifiers: new Uint8Array([3, 0]),
    }
    const d = decodeYearlyClimate(toBuffer(payload))
    expect(uccCode(d, 0, true)).toBe('Ts-xw') // temperate · semi-arid + both modifiers
    expect(uccCode(d, 1, false)).toBe('Ro') // ocean
    expect(uccCode(d, 1, true)).toBe('Rn') // land n/a → explicit n slot
  })

  it('composes v2 codes (A/C/D/E alphabet, l/g/H modifiers, m/d/h/o suffixes)', () => {
    const payload = {
      ...basePayload(),
      profile: 'ucc-v2',
      thermal_bands: ['polar', 'cold', 'temperate', 'tropical'],
      supply_bands: ['arid', 'semi_arid', 'transitional', 'humid'],
      ucc_thermal: new Uint8Array([1, 2, 0]),
      ucc_supply: new Uint8Array([1, 2, 255]),
      ucc_supply_status: new Uint8Array([0, 0, 4]),
      ucc_modifiers: new Uint8Array([7, 0, 0]),
      shape_codes: ['unimodal', 'bimodal'],
      phase_codes: ['in_phase', 'anti_phase'],
      ucc_shape: new Uint8Array([0, 255, 0]),
      ucc_phase: new Uint8Array([1, 255, 255]),
      p_harmonic1: new Uint8Array(new Float32Array([0.5, 0.4, 0.1]).buffer),
      p_harmonic2: new Uint8Array(new Float32Array([0.2, 0.3, 0.05]).buffer),
      p_phase: new Uint8Array(new Float32Array([-0.45, NaN, NaN]).buffer),
      p_phase_status: new Uint8Array([0, 1, 1]),
      climate_state: 'runaway_greenhouse',
      lapse_rate_c_per_km: 8.0,
    }
    const d = decodeYearlyClimate(toBuffer(payload))
    // cold · semi-arid (p), all modifiers (l,g,H), unimodal wet season (m),
    // anti-phase rain (o) — one dash, letters concatenated.
    expect(uccCode(d, 0, true)).toBe('Dp-lgHmo')
    // temperate · transitional, no letters → bare code.
    expect(uccCode(d, 1, true)).toBe('Ct')
    // polar land with invalid supply (e.g. ice cap OOD) → explicit n slot;
    // the shape letter survives the domain gate (precipitation seasonality is
    // independent of the demand model's validity).
    expect(uccCode(d, 2, true)).toBe('En-m')
    // New descriptor fields decode (NaN travels).
    expect(d.pHarmonic1![0]).toBeCloseTo(0.5)
    expect(Number.isNaN(d.pPhase![1])).toBe(true)
    expect(d.pPhaseStatus![1]).toBe(1)
    // World-level declarations decode.
    expect(d.climateState).toBe('runaway_greenhouse')
    expect(d.lapseRateCPerKm).toBe(8.0)
  })
})
