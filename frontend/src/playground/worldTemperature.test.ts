import { describe, expect, it } from 'vitest'
import { EARTH_PARAMS, isTemperatureParams } from './temperatureDraft'
import { temperatureInputCatalog, worldTemperatureParams } from './worldTemperature'

describe('world temperature trial inputs', () => {
  it('uses a moon’s own surface settings but its host’s orbit around the star', () => {
    const trial = worldTemperatureParams({
      stars: [{ id: 'star_ignis', luminosity_sol: 0.1227 }],
      bodies: [
        { id: 'planet_aegis', parent_id: 'star_ignis', orbit: { semi_major_axis_au: 0.3648, period_days: 99.7025 } },
        { id: 'satellite_nacrea', name: 'Nacrea', parent_id: 'planet_aegis', orbit: { semi_major_axis_au: 0.004835, period_days: 3.1383 },
          physical: { axial_tilt_deg: 19.9, rotation_period_days: 3.1336, albedo: 0.3 }, atmosphere: { greenhouse_factor: 35 } },
      ],
    }, 'satellite_nacrea')
    expect(trial).toMatchObject({ name: 'Nacrea', defaults: false, params: {
      luminosity: 0.1227, distanceAu: 0.3648, yearDays: 99.7025, tiltDeg: 19.9,
      rotationDays: 3.1336, albedo: 0.3, greenhouseK: 35,
    } })
    expect(isTemperatureParams(trial.params)).toBe(true)
  })

  it('reports missing inputs and accepts the magnitude of retrograde rotation and seasonal tilt', () => {
    const trial = worldTemperatureParams({ bodies: [
      { id: 'venus', physical: { axial_tilt_deg: 177, rotation_period_days: -243, albedo: 0.689 } },
    ] }, 'venus')
    expect(trial).toMatchObject({ defaults: true, params: { tiltDeg: 3, rotationDays: 243, luminosity: EARTH_PARAMS.luminosity } })
    expect(isTemperatureParams(trial.params)).toBe(true)
  })

  it('reads available template settings before the world has a derived catalog', () => {
    const input = temperatureInputCatalog({ stars: [{ id: 'star', luminosity: 0.8 }],
      orbits: [{ body_id: 'gaia', parent_id: 'star', semi_major_axis_au: 0.9 }] },
    [{ id: 'gaia', name: 'Gaia', albedo: 0.25, axial_tilt_deg: 23.4, rotation_period_days: 1.1,
      atmosphere: { greenhouse_factor: 30 } }])
    expect(worldTemperatureParams(input, 'gaia')).toMatchObject({ name: 'Gaia', defaults: true, params: {
      luminosity: 0.8, distanceAu: 0.9, yearDays: EARTH_PARAMS.yearDays,
      albedo: 0.25, tiltDeg: 23.4, rotationDays: 1.1, greenhouseK: 30,
    } })
  })

})
