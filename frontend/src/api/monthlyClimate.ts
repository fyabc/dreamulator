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
  /** Monthly wind east/north components (tech debt 24); absent in old files. */
  windEastMonthly?: Float32Array
  windNorthMonthly?: Float32Array
  windMaxSpeedMs?: number
  /** Monthly monsoon pressure anomaly ΔP (hPa); absent in old files. */
  pressureMonthly?: Float32Array
  pressureRangeHpa?: [number, number]
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

  // int16 (current) vs float32 (legacy): the backend now quantizes every monthly
  // field to int16 + a per-field (scale, offset); older files store raw float32
  // and carry no scale/offset keys.  This handles both transparently.
  const isInt16 = obj.dtype === 'int16'

  /** Decode one field — dequantize int16, or reinterpret float32 (legacy). */
  const toF32 = (u8: Uint8Array, scale?: unknown, offset?: unknown): Float32Array => {
    if (isInt16 && typeof scale === 'number' && typeof offset === 'number') {
      const i16 = new Int16Array(u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength))
      const out = new Float32Array(i16.length)
      for (let i = 0; i < i16.length; i++) out[i] = i16[i] * scale + offset
      return out
    }
    return toFloat32(u8)
  }

  const out: MonthlyClimateData = {
    numCells,
    months,
    tMonthly: toF32(obj.t_monthly as Uint8Array, obj.t_scale, obj.t_offset),
    pMonthly: toF32(obj.p_monthly as Uint8Array, obj.p_scale, obj.p_offset),
    temperatureRangeC: obj.temperature_range_c as [number, number],
    precipitationRangeMm: obj.precipitation_range_mm as [number, number],
  }
  if (obj.wind_east_monthly instanceof Uint8Array) {
    out.windEastMonthly = toF32(obj.wind_east_monthly, obj.wind_east_scale, obj.wind_east_offset)
    out.windNorthMonthly = toF32(obj.wind_north_monthly as Uint8Array, obj.wind_north_scale, obj.wind_north_offset)
    out.windMaxSpeedMs = obj.wind_max_speed_m_s as number
  }
  if (obj.pressure_monthly instanceof Uint8Array) {
    out.pressureMonthly = toF32(obj.pressure_monthly, obj.pressure_scale, obj.pressure_offset)
    out.pressureRangeHpa = obj.pressure_range_hpa as [number, number]
  }
  return out
}
