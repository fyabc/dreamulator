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
  return {
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
}
