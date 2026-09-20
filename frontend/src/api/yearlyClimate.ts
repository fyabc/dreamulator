/**
 * Yearly climate descriptors — decode + typed view over the backend's
 * `climate_yearly.msgpack` (UCC-01 step 2: continuous UCC descriptors).
 *
 * The backend packs per-cell float32 arrays (mesh cell order) computed by
 * `ucc.compute_descriptors` from the monthly series, plus uint8 status codes
 * carrying *why* a value is undefined (ucc-review §4.4).  Undefined values are
 * NaN — always check the status / NaN before displaying a number.
 */

import { decode } from '@msgpack/msgpack'

export interface YearlyClimateData {
  numCells: number
  months: number
  formatVersion: string
  /** Reference-demand model behind AI/deficit (e.g. 'hamon-1961'). */
  demandModel: string
  /** Threshold (°C) for the time-fraction-below statistic. */
  freezeThresholdC: number
  /** status code index → name (e.g. 'valid', 'missing_input', …). */
  statusCodes: string[]
  /** Duration-weighted mean temperature, °C. */
  tMeanC: Float32Array
  /** Coldest bin-mean temperature, °C. */
  tMinC: Float32Array
  /** Hottest bin-mean temperature, °C. */
  tMaxC: Float32Array
  /** tMax − tMin, °C. */
  tRangeC: Float32Array
  /** Time fraction of bin means below freezeThresholdC. */
  tBelowFrac: Float32Array
  /** Mean precipitation rate, mm per reference month. */
  pMeanMmPerMonth: Float32Array
  /** Total precipitation, mm per reference year. */
  pTotalMm: Float32Array
  /** Aridity index P/Eref over the window; NaN unless status is 'valid'. */
  ai: Float32Array
  aiStatus: Uint8Array
  /** Same-period seasonal deficit fraction; NaN unless status is 'valid'. */
  deficit: Float32Array
  deficitStatus: Uint8Array
  /** Precipitation concentration C_TV; NaN when there is no precipitation. */
  concentration: Float32Array
  // --- Classification (UCC-01 step 4a) — optional: older exports predate the
  // frozen profile, so every field below may be absent (layer then degrades to
  // fully transparent and the panel hides the class row).
  /** Frozen profile identifier (e.g. 'ucc-v0'). */
  profile?: string
  /** Thermal band index → name (e.g. 'polar', 'cold', 'temperate', 'tropical'). */
  thermalBands?: string[]
  /** Supply band index → name (e.g. 'arid', 'transitional', 'humid'). */
  supplyBands?: string[]
  /** Per-cell thermal band index into thermalBands. */
  uccThermal?: Uint8Array
  /** Per-cell supply band index into supplyBands; 255 = not applicable. */
  uccSupply?: Uint8Array
  /** Per-cell supply-axis status code (index into statusCodes). */
  uccSupplyStatus?: Uint8Array
  /** Per-cell modifier bitmask: bit 0 = continental, bit 1 = water_stress. */
  uccModifiers?: Uint8Array
}

/** Reinterpret a MessagePack `bin` (Uint8Array) as little-endian float32. */
function toFloat32(u8: Uint8Array): Float32Array {
  return new Float32Array(u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength))
}

/** Reinterpret a MessagePack `bin` (Uint8Array) as uint8 (copy-free view). */
function toUint8(u8: Uint8Array): Uint8Array {
  return new Uint8Array(u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength))
}

export function decodeYearlyClimate(raw: ArrayBuffer): YearlyClimateData {
  const obj = decode(raw) as Record<string, unknown>
  const out: YearlyClimateData = {
    numCells: obj.num_cells as number,
    months: obj.months as number,
    formatVersion: (obj.format_version as string) ?? '',
    demandModel: (obj.demand_model as string) ?? '',
    freezeThresholdC: (obj.freeze_threshold_c as number) ?? 0,
    statusCodes: (obj.status_codes as string[]) ?? [],
    tMeanC: toFloat32(obj.t_mean_c as Uint8Array),
    tMinC: toFloat32(obj.t_min_c as Uint8Array),
    tMaxC: toFloat32(obj.t_max_c as Uint8Array),
    tRangeC: toFloat32(obj.t_range_c as Uint8Array),
    tBelowFrac: toFloat32(obj.t_below_frac as Uint8Array),
    pMeanMmPerMonth: toFloat32(obj.p_mean_mm_per_month as Uint8Array),
    pTotalMm: toFloat32(obj.p_total_mm as Uint8Array),
    ai: toFloat32(obj.ai as Uint8Array),
    aiStatus: toUint8(obj.ai_status as Uint8Array),
    deficit: toFloat32(obj.deficit as Uint8Array),
    deficitStatus: toUint8(obj.deficit_status as Uint8Array),
    concentration: toFloat32(obj.concentration as Uint8Array),
  }
  // Classification fields (UCC-01 step 4a) are absent in older exports.
  if (obj.ucc_thermal !== undefined) {
    out.profile = (obj.profile as string) ?? ''
    out.thermalBands = (obj.thermal_bands as string[]) ?? []
    out.supplyBands = (obj.supply_bands as string[]) ?? []
    out.uccThermal = toUint8(obj.ucc_thermal as Uint8Array)
    out.uccSupply = toUint8(obj.ucc_supply as Uint8Array)
    out.uccSupplyStatus = toUint8(obj.ucc_supply_status as Uint8Array)
    out.uccModifiers = toUint8(obj.ucc_modifiers as Uint8Array)
  }
  return out
}
