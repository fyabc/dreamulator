import { GRID_H, GRID_W, type PlanetParams } from './temperatureDraft'
import type { TemperatureRequest } from './temperature.worker'

export function temperatureRequest(elevation: TemperatureRequest['elevation'], params: PlanetParams): TemperatureRequest {
  return { elevation, runtimeBase: new URL(`${import.meta.env.BASE_URL}${__PLAYGROUND_RUNTIME_PATH__}`, document.baseURI).href,
    params: { width: GRID_W, height: GRID_H, sea_level_m: params.seaLevelM, stellar_luminosity_sol: params.luminosity,
      orbital_distance_au: params.distanceAu, albedo: params.albedo, greenhouse_warming_K: params.greenhouseK,
      axial_tilt_deg: params.tiltDeg, orbital_period_days: params.yearDays, rotation_period_days: params.rotationDays,
      variable_lapse_rate: params.variableLapse } }
}
