/**
 * Monthly climate data — decode + typed view over the backend's
 * `climate_monthly.msgpack` (Phase 4 monthly display).
 *
 * The backend packs two per-cell N×12 float32 arrays (temperature °C and
 * precipitation mm/month, in mesh cell order) plus range metadata.  This module
 * decodes the MessagePack and exposes the arrays as Float32Array for the layer
 * bake in `layerBakes.ts`.
 */

import { decode } from '@msgpack/msgpack'

export interface MonthlyClimateData {
  numCells: number
  months: number
  /** numCells × months, row-major (cell i, month m → index i * months + m). */
  tMonthly: Float32Array
  pMonthly: Float32Array
  temperatureRangeC: [number, number]
  precipitationRangeMm: [number, number]
}

/**
 * Reinterpret a MessagePack `bin` (Uint8Array) as little-endian float32.
 * `slice` normalises the byte offset to 0 so the Float32Array view is aligned.
 */
function toFloat32(u8: Uint8Array): Float32Array {
  return new Float32Array(u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength))
}

export function decodeMonthlyClimate(raw: ArrayBuffer): MonthlyClimateData {
  const obj = decode(raw) as Record<string, unknown>
  const numCells = obj.num_cells as number
  const months = obj.months as number
  return {
    numCells,
    months,
    tMonthly: toFloat32(obj.t_monthly as Uint8Array),
    pMonthly: toFloat32(obj.p_monthly as Uint8Array),
    temperatureRangeC: obj.temperature_range_c as [number, number],
    precipitationRangeMm: obj.precipitation_range_mm as [number, number],
  }
}
