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
