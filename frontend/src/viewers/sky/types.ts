/** Types mirroring the backend sky-ephemeris payloads (snake_case, as-is).
 *
 * Source of truth: `src/dreamulator/engine/ephemeris.py` (Pydantic
 * SkyEphemerisResult / TargetPosition), served verbatim by
 * `GET /api/worlds/{world}/sky`.
 */

export interface TargetPosition {
  body_id: string
  name: string | null
  altitude_deg: number
  azimuth_deg: number
  ecliptic_lon_deg: number
  ecliptic_lat_deg: number
  equatorial_ra_deg: number
  equatorial_dec_deg: number
  distance_km: number
  angular_diameter_deg: number
  phase_angle_deg: number | null
  illuminated_fraction: number | null
  phase_function: number | null
  apparent_magnitude: number
  illuminance_w_m2: number
  elongation_star_deg: number | null
  elongation_parent_deg: number | null
  altitude_rate_deg_per_hr: number
  rise_state: string | null
  next_rise_days: number | null
  next_set_days: number | null
}

export interface SkyEphemerisResult {
  observer_id: string
  lat_deg: number
  lon_deg: number
  at_days: number
  solar_day_days: number | null
  spin_source: string | null
  targets: TargetPosition[]
}

/** The catalog slices the sky page consumes (via api.getSystemCatalog). */
export interface SkyCatalogStar {
  id: string
  name?: string | null
  spectral_class?: string | null
  temperature_k?: number | null
  radius_sol?: number | null
  luminosity_sol?: number | null
}

export interface SkyCatalogBody {
  id: string
  name?: string | null
  body_type?: string | null
  parent_id?: string | null
  physical?: {
    rotation_period_days?: number | null
    axial_tilt_deg?: number | null
    radius_km?: number | null
  } | null
  derived?: {
    tidally_locked?: boolean | null
    solar_day_days?: number | null
    spin_axis_ecliptic_longitude_deg?: number | null
  } | null
  orbit?: { period_days?: number | null } | null
}

export interface SkyCatalog {
  stars?: SkyCatalogStar[] | null
  bodies?: SkyCatalogBody[] | null
  target_body_id?: string | null
}

/** Mirror of derived/sky_background.yaml (the universe setting). */
export interface SkyBackgroundStar {
  id: string
  name: string | null
  magnitude: number
  temperature_k: number
  unit: [number, number, number]
  source: 'authored' | 'starfield'
  variability: {
    type: string
    magnitude_range: [number, number] | null
    period_days: number | null
  } | null
}

export interface SkyBackgroundDso {
  id: string
  name: string | null
  type: 'nebula' | 'cluster' | 'galaxy' | 'remnant'
  magnitude: number
  angular_size_deg: number
  unit: [number, number, number]
}

export interface SkyBackground {
  frame: 'ecliptic'
  starfield: { seed: number; count: number; magnitude_limit: number }
  stars: SkyBackgroundStar[]
  deep_sky: SkyBackgroundDso[]
  galactic_band: { pole_unit: [number, number, number]; width_deg: number; brightness: number } | null
  transient_events: Array<{
    id: string
    type: 'supernova' | 'grb'
    unit: [number, number, number]
    epoch_window_days: [number, number] | null
    peak_magnitude: number | null
    rate_per_myr: number | null
  }>
  wandering_objects: Array<{
    id: string
    name: string | null
    object_type: string
    unit: [number, number, number]
    distance_pc: number
    magnitude: number | null
    close_approach_au: number | null
    encounter_age_myr: number | null
  }>
}

/** Mirror of derived/sky_culture.yaml (the civilization layer's star lore).
 *  Cultures reference background objects by id only — positions are joined
 *  against the SkyBackground catalogue client-side, never copied here. */
export interface SkyCultureAsterism {
  id: string
  name: string
  meaning: string | null
  /** Edges as pairs of background-object ids (authored star or deep-sky). */
  lines: Array<[string, string]>
}

export interface SkyCultureEntry {
  id: string
  name: string
  description: string | null
  /** Background-star id -> this culture's proper name for it. */
  star_names: Record<string, string>
  asterisms: SkyCultureAsterism[]
}

export interface SkyCulture {
  cultures: SkyCultureEntry[]
}
