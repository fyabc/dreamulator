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
  /** First/second circular-harmonic amplitude of the precipitation mass
   * (v2-α seasonality shape: R2 > R1 = bimodal wet seasons); NaN without
   * precipitation. */
  pHarmonic1?: Float32Array
  pHarmonic2?: Float32Array
  /** Signed rain–demand phase as a fraction of the seasonal cycle in
   * (−0.5, 0.5] (0 = in phase, ±0.5 = anti-phase); NaN unless the status is
   * 'valid'. */
  pPhase?: Float32Array
  pPhaseStatus?: Uint8Array
  // --- Classification (UCC-01 step 4a) — optional: older exports predate the
  // frozen profile, so every field below may be absent (layer then degrades to
  // fully transparent and the panel hides the class row).
  /** Frozen profile identifier (e.g. 'ucc-v0'). */
  profile?: string
  /** 'model' (engine-built world) or 'observation' (earth root's obs-derived
   *  file from scripts/earth/export_earth_yearly.py). */
  dataSource?: string
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
  /** Per-cell modifier bitmask: bit 0 = continental, bit 1 = water_stress,
   * bit 2 = highland (-H, v2: sea-level-reduced thermal band differs). */
  uccModifiers?: Uint8Array
  /** shape/phase letter code lists (v2 exports); per-cell index, 255 = none. */
  shapeCodes?: string[]
  phaseCodes?: string[]
  uccShape?: Uint8Array
  uccPhase?: Uint8Array
  // --- Declarations (data & model semantics, shown on demand in the cell
  // inspector).  bin_days/window_days/provenance are written by the solar
  // importers and the obs-derived earth file; engine exports predate them and
  // fall back to the result-contract reference month/year below.
  /** Days per climate bin. */
  binDays?: number
  /** Total span of the bins, days. */
  windowDays?: number
  /** Hamon day-length assumption (h), written alongside demand_model. */
  demandDaylengthH?: number
  /** Free-text provenance entries (dataset, temperature kind, declared-zero
   *  precipitation, …); the key set varies by body. */
  provenance?: Record<string, unknown>
  /** Result-contract reference year / month (days), from shared metadata. */
  referenceYearDays?: number
  referenceMonthDays?: number
  /** World-level climate-state declaration (axis F vocabulary, e.g.
   * 'temperate', 'runaway_greenhouse'); absent when not declared. */
  climateState?: string
  /** Declared environmental lapse rate (K/km) behind the -H modifier;
   * absent for airless worlds (no lapse rate exists). */
  lapseRateCPerKm?: number
}

/** Reinterpret a MessagePack `bin` (Uint8Array) as little-endian float32. */
function toFloat32(u8: Uint8Array): Float32Array {
  return new Float32Array(u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength))
}

/** Reinterpret a MessagePack `bin` (Uint8Array) as uint8 (copy-free view). */
function toUint8(u8: Uint8Array): Uint8Array {
  return new Uint8Array(u8.buffer.slice(u8.byteOffset, u8.byteOffset + u8.byteLength))
}

// Compact display codes — mirror of THERMAL_CODE_LETTERS(_V2) / SUPPLY_CODE_
// LETTERS / MOD_CODE_LETTERS(_V2) in src/dreamulator/map/ucc.py (single source
// of truth is the Python side; codes are versioned with the profile and are
// NOT Köppen letters).  v1: P/C/T/R + x/w.  v2: Köppen-direction A/C/D/E with
// B permanently blank, modifiers l/g/H (H = highland, elevation-made band),
// suffix letters m/d (wet-season shape) and h/o (rain–demand phase).
const UCC_THERMAL_LETTERS_V1: Record<string, string> = {
  polar: 'P',
  cold: 'C',
  temperate: 'T',
  tropical: 'R',
}
const UCC_THERMAL_LETTERS_V2: Record<string, string> = {
  tropical: 'A',
  temperate: 'C',
  cold: 'D',
  polar: 'E',
}
const UCC_SUPPLY_LETTERS_V1: Record<string, string> = {
  arid: 'a',
  semi_arid: 's',
  transitional: 't',
  humid: 'h',
}
// v2: a/p/t/u — alphabetically ascending with wetness; s retired (with v2's
// thermal C meaning temperate, UCC "Cs" would read as Köppen's temperate
// dry-summer), h retired (double duty with the in-phase suffix; Köppen BWh's
// h means *hot* against our humid).
const UCC_SUPPLY_LETTERS_V2: Record<string, string> = {
  arid: 'a',
  semi_arid: 'p',
  transitional: 't',
  humid: 'u',
}
const UCC_SHAPE_LETTERS: Record<string, string> = { unimodal: 'm', bimodal: 'd' }
const UCC_PHASE_LETTERS: Record<string, string> = { in_phase: 'h', anti_phase: 'o' }

/** Compose a cell's short UCC code (v1 e.g. `Rh`, `Cs-xw`; v2 e.g. `Ct-mh`,
 * `Dp-lgmo`, `An` hot-side OOD, `Eo` polar ocean) from the decoded yearly
 * data.  Null when the file predates the classification fields. */
export function uccCode(d: YearlyClimateData, i: number, isLand: boolean): string | null {
  const { uccThermal, uccSupply, uccModifiers, thermalBands, supplyBands } = d
  if (!uccThermal || !thermalBands || !supplyBands) return null
  const v2 = (d.profile ?? '').startsWith('ucc-v2')
  const thermalLetters = v2 ? UCC_THERMAL_LETTERS_V2 : UCC_THERMAL_LETTERS_V1
  const supplyLetters = v2 ? UCC_SUPPLY_LETTERS_V2 : UCC_SUPPLY_LETTERS_V1
  const t = thermalLetters[thermalBands[uccThermal[i]]]
  if (!t) return null
  const sIdx = uccSupply ? uccSupply[i] : 255
  let code = t
  if (sIdx === 255) {
    code += isLand ? 'n' : 'o'
  } else {
    code += supplyLetters[supplyBands[sIdx]] ?? ''
  }
  const mods = uccModifiers ? uccModifiers[i] : 0
  let suffix = v2
    ? (mods & 1 ? 'l' : '') + (mods & 2 ? 'g' : '') + (mods & 4 ? 'H' : '')
    : (mods & 1 ? 'x' : '') + (mods & 2 ? 'w' : '')
  if (v2 && d.uccShape && d.shapeCodes) {
    const s = d.uccShape[i]
    if (s !== 255) suffix += UCC_SHAPE_LETTERS[d.shapeCodes[s]] ?? ''
  }
  if (v2 && d.uccPhase && d.phaseCodes) {
    const p = d.uccPhase[i]
    if (p !== 255) suffix += UCC_PHASE_LETTERS[d.phaseCodes[p]] ?? ''
  }
  return suffix ? `${code}-${suffix}` : code
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
    pHarmonic1: obj.p_harmonic1 ? toFloat32(obj.p_harmonic1 as Uint8Array) : undefined,
    pHarmonic2: obj.p_harmonic2 ? toFloat32(obj.p_harmonic2 as Uint8Array) : undefined,
    pPhase: obj.p_phase ? toFloat32(obj.p_phase as Uint8Array) : undefined,
    pPhaseStatus: obj.p_phase_status ? toUint8(obj.p_phase_status as Uint8Array) : undefined,
    ai: toFloat32(obj.ai as Uint8Array),
    aiStatus: toUint8(obj.ai_status as Uint8Array),
    deficit: toFloat32(obj.deficit as Uint8Array),
    deficitStatus: toUint8(obj.deficit_status as Uint8Array),
    concentration: toFloat32(obj.concentration as Uint8Array),
  }
  // Provenance: 'model' (engine-built) vs 'observation' (earth root) vs
  // 'gcm-climatology' (solar reference bodies).  Absent on exports predating
  // the marker.
  out.dataSource = (obj.data_source as string) ?? undefined
  // Declarations: time basis + demand day-length + free-text provenance.
  out.binDays = (obj.bin_days as number) ?? undefined
  out.windowDays = (obj.window_days as number) ?? undefined
  out.demandDaylengthH = (obj.demand_daylength_h as number) ?? undefined
  out.provenance = (obj.provenance as Record<string, unknown>) ?? undefined
  const time = obj.time as { reference_year_days?: number; reference_month_days?: number } | undefined
  out.referenceYearDays = time?.reference_year_days
  out.referenceMonthDays = time?.reference_month_days
  out.climateState = (obj.climate_state as string) ?? undefined
  out.lapseRateCPerKm = (obj.lapse_rate_c_per_km as number) ?? undefined
  // Classification fields (UCC-01 step 4a) are absent in older exports.
  if (obj.ucc_thermal !== undefined) {
    out.profile = (obj.profile as string) ?? ''
    out.thermalBands = (obj.thermal_bands as string[]) ?? []
    out.supplyBands = (obj.supply_bands as string[]) ?? []
    out.uccThermal = toUint8(obj.ucc_thermal as Uint8Array)
    out.uccSupply = toUint8(obj.ucc_supply as Uint8Array)
    out.uccSupplyStatus = toUint8(obj.ucc_supply_status as Uint8Array)
    out.uccModifiers = toUint8(obj.ucc_modifiers as Uint8Array)
    out.shapeCodes = (obj.shape_codes as string[]) ?? undefined
    out.phaseCodes = (obj.phase_codes as string[]) ?? undefined
    out.uccShape = obj.ucc_shape ? toUint8(obj.ucc_shape as Uint8Array) : undefined
    out.uccPhase = obj.ucc_phase ? toUint8(obj.ucc_phase as Uint8Array) : undefined
  }
  return out
}
