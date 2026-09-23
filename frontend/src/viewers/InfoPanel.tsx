/**
 * InfoPanel — HTML overlay showing details of the selected star or planet.
 *
 * Field grouping follows the conventions of comparable applications
 * (researched 2026-09-23): NASA Eyes' "vital statistics" (physical facts
 * grouped with day/year length, moons, atmosphere), Stellarium's object
 * info (orbital elements + physical ephemerides) and Celestia's HUD
 * readouts (radius, mass, sidereal day, temperature, luminosity).
 *
 * Sections: overview → orbit → physical → rotation & seasons →
 * atmosphere & hydrosphere → insolation & thermal → lithosphere →
 * terrain summary.  The always-available basics come from the viewer's
 * PlanetData / StarData; the rich fields come from the system catalog
 * (CatalogBody / CatalogBody.derived), passed down by the page.
 */

import { Link } from 'react-router-dom'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { StarData } from './StarMesh'
import type { PlanetData } from './PlanetMesh'
import { formatRadius, formatMass } from './utils/scale'
import type { CVTMesh } from './map/types'
import type { CatalogBody, CatalogStar } from '../api/catalogAdapter'

type SelectedBody =
  | { type: 'star'; data: StarData }
  | { type: 'planet'; data: PlanetData }
  | null

interface InfoPanelProps {
  selected: SelectedBody
  onClose: () => void
  /** World name — enables the "3D globe" link when a planet is selected. */
  worldName?: string
  /** Current branch search-param string (e.g. "?branch=foo"). */
  branchQS?: string
  /** Set of planet IDs that have 2D map / globe data. */
  mapPlanetIds?: Set<string>
  /** CVT mesh for the selected planet — enables terrain summary section. */
  cvtMesh?: CVTMesh | null
  /** System-catalog entry for the selected body (rich physical/derived fields). */
  catalogBody?: CatalogBody
  /** System-catalog entry for the selected star (age / evolution / HZ bounds). */
  catalogStar?: CatalogStar
  /** Display name of the parent body this one orbits (e.g. "Sol", "Earth"). */
  parentName?: string
  /** How many satellites orbit this body. */
  satelliteCount?: number
  /** "Focus & zoom in": camera flies to the body and dollies to close range. */
  onFocus?: () => void
}

const PLANET_TYPE_LABELS: Record<string, string> = {
  terrestrial: 'planetType.terrestrial',
  gas_giant: 'planetType.gas_giant',
  ice_giant: 'planetType.ice_giant',
  ocean_world: 'planetType.ocean_world',
  dwarf: 'planetType.dwarf',
}

function InfoRow({ label, value }: { label: string; value: string | number | undefined }) {
  if (value == null) return null
  return (
    <div className="flex justify-between gap-4 text-sm py-px">
      <span className="text-gray-500">{label}</span>
      <span className="text-gray-200 font-mono text-right">{value}</span>
    </div>
  )
}

/** Section heading — a thin separator plus a small uppercase label. */
function Section({ title }: { title: string }) {
  return (
    <div className="mt-2 pt-2 border-t border-space-border">
      <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
        {title}
      </div>
    </div>
  )
}

/** Significance-trimmed number without trailing-zero noise (3 s.f. default). */
function sig(x: number, precision = 3): string {
  return String(parseFloat(x.toPrecision(precision)))
}

export default function InfoPanel({
  selected,
  onClose,
  worldName,
  branchQS,
  mapPlanetIds,
  cvtMesh,
  catalogBody,
  catalogStar,
  parentName,
  satelliteCount,
  onFocus,
}: InfoPanelProps) {
  const { t } = useTranslation('map')
  const [terrainOpen, setTerrainOpen] = useState(false)

  if (!selected) return null

  // Duration formatting: long periods gain a year figure, sub-2-day ones
  // gain hours (Stellarium-style contextual precision).
  const fmtDuration = (d?: number | null): string | undefined => {
    if (d == null) return undefined
    let s = `${sig(d)} ${t('unit.days')}`
    if (d >= 400) s += ` (${sig(d / 365.25)} ${t('unit.years')})`
    else if (d > 0 && d < 2) s += ` (${sig(d * 24)} h)`
    return s
  }

  return (
    <div
      className="absolute bottom-4 right-4 z-10 w-80"
      style={{ pointerEvents: 'auto' }}
    >
      <div className="glass-panel p-4 max-h-[70vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div>
            <span className="text-xs px-1.5 py-0.5 rounded bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/20 mr-2">
              {selected.type === 'star' ? t('info.star') : t('info.planet')}
            </span>
            <span className="font-semibold text-neon-cyan">
              {selected.data.name}
            </span>
          </div>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-200 transition-colors p-1"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Action buttons — at the top so they're reachable without scrolling
            through the field sections */}
        {selected.type === 'planet' && worldName && (
          <div className="mb-3 flex gap-2">
            {onFocus && (
              <button
                onClick={onFocus}
                className="flex-1 text-center px-2 py-1.5 text-xs rounded bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors"
              >
                {t('info.focusButton')}
              </button>
            )}
            {mapPlanetIds?.has(selected.data.id) && (
              <Link
                to={`/worlds/${worldName}/globe/${selected.data.id}${branchQS ?? ''}`}
                onClick={onClose}
                className="flex-1 text-center px-2 py-1.5 text-xs rounded bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors"
              >
                {t('info.globe3d')}
              </Link>
            )}
            {mapPlanetIds?.has(selected.data.id) && (
              <Link
                to={`/worlds/${worldName}/map/${selected.data.id}${branchQS ?? ''}`}
                onClick={onClose}
                className="flex-1 text-center px-2 py-1.5 text-xs rounded bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors"
              >
                {t('info.map2d')}
              </Link>
            )}
          </div>
        )}

        {/* Star details */}
        {selected.type === 'star' && (() => {
          const star = selected.data
          const cat = catalogStar
          const temp = star.derived?.computed_temperature ?? star.temperature ?? cat?.temperature_k
          const radius = star.derived?.computed_radius ?? star.radius ?? cat?.radius_sol
          const lum = star.derived?.computed_luminosity ?? star.luminosity ?? cat?.luminosity_sol
          const mass = star.mass ?? cat?.mass_sol
          const hz = cat?.habitable_zone
          return (
            <>
              <div className="space-y-0.5">
                <InfoRow label={t('info.spectralType')} value={`${star.spectral_class ?? cat?.spectral_class ?? 'N/A'} ${star.luminosity_class ?? cat?.luminosity_class ?? ''}`} />
                <InfoRow label={t('info.temperature')} value={temp != null ? `${Math.round(temp)} K` : undefined} />
                <InfoRow label={t('info.radius')} value={radius != null ? `${radius.toFixed(3)} R☉` : undefined} />
                <InfoRow label={t('info.luminosity')} value={lum != null ? `${lum.toFixed(4)} L☉` : undefined} />
                <InfoRow label={t('info.mass')} value={mass != null ? `${mass.toFixed(3)} M☉` : undefined} />
              </div>

              {(cat?.age_gyr != null || cat?.ms_lifetime_gyr != null || cat?.evolution_progress != null) && (
                <Section title={t('info.sectionEvolution')} />
              )}
              <div className="space-y-0.5">
                <InfoRow label={t('info.age')} value={cat?.age_gyr != null ? `${sig(cat.age_gyr)} Gyr` : undefined} />
                <InfoRow label={t('info.msLifetime')} value={cat?.ms_lifetime_gyr != null ? `${sig(cat.ms_lifetime_gyr)} Gyr` : undefined} />
                <InfoRow label={t('info.evolutionProgress')} value={cat?.evolution_progress != null ? `${(cat.evolution_progress * 100).toFixed(1)}%` : undefined} />
              </div>

              {hz && (
                <>
                  <Section title={t('info.sectionHZ')} />
                  <div className="space-y-0.5">
                    <InfoRow
                      label={t('info.habitableZoneRange')}
                      value={hz.recent_venus_au != null && hz.early_mars_au != null
                        ? `${sig(hz.recent_venus_au)} – ${sig(hz.early_mars_au)} AU`
                        : undefined}
                    />
                    <InfoRow label={t('info.habitableZoneCenter')} value={cat?.habitable_zone_center_au != null ? `${sig(cat.habitable_zone_center_au)} AU` : undefined} />
                  </div>
                </>
              )}
            </>
          )
        })()}

        {/* Planet details */}
        {selected.type === 'planet' && (() => {
          const planet = selected.data
          const cat = catalogBody
          const physical = cat?.physical
          const derived = cat?.derived
          const typeKey = planet.planet_type ? PLANET_TYPE_LABELS[planet.planet_type] : undefined
          const typeLabel = typeKey ? t(typeKey) : (planet.planet_type ?? 'N/A')

          // Radius: R⊕ (or km for small bodies), with the km figure appended
          const radiusValue = (() => {
            const base = formatRadius(planet.radius)
            const km = physical?.radius_km
            if (planet.radius >= 0.01 && km != null) {
              return `${base} (${km.toLocaleString(undefined, { maximumFractionDigits: 0 })} km)`
            }
            return base
          })()

          // Atmosphere composition: top-3 components, descending
          const composition = (() => {
            const comp = cat?.atmosphere?.composition
            if (!comp) return undefined
            const parts = Object.entries(comp)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 3)
              .map(([k, v]) => `${k} ${(v * 100).toFixed(1)}%`)
            return parts.length > 0 ? parts.join(' · ') : undefined
          })()

          // Semi-major axis: AU with a km/Mkm equivalent
          const orbit = cat?.orbit
          const semiMajorStr = (() => {
            const a = orbit?.semi_major_axis_au
            if (a == null) return undefined
            return a >= 0.01
              ? `${sig(a)} AU (${sig(a * 149.5979, 4)} Mkm)`
              : `${sig(a)} AU (${Math.round(a * 149_597_870.7).toLocaleString()} km)`
          })()

          return (
            <>
              <div className="space-y-0.5">
                <InfoRow label={t('info.type')} value={typeLabel} />
                <InfoRow label={t('info.mass')} value={formatMass(planet.mass)} />
                <InfoRow label={t('info.radius')} value={radiusValue} />
                <InfoRow label={t('info.albedo')} value={planet.albedo} />
                <InfoRow label={t('info.satellites')} value={(satelliteCount ?? 0) > 0 ? satelliteCount : undefined} />
              </div>

              {/* Orbit — elements from the same source the orbit lines use */}
              {orbit && (
                <>
                  <Section title={t('info.sectionOrbit')} />
                  <div className="space-y-0.5">
                    <InfoRow label={t('info.orbitParent')} value={parentName} />
                    <InfoRow label={t('info.semiMajorAxis')} value={semiMajorStr} />
                    <InfoRow label={t('info.eccentricity')} value={orbit.eccentricity != null ? sig(orbit.eccentricity) : undefined} />
                    <InfoRow label={t('info.inclination')} value={orbit.inclination_deg != null ? `${sig(orbit.inclination_deg)}°` : undefined} />
                    <InfoRow label={t('info.orbitalPeriod')} value={fmtDuration(orbit.period_days)} />
                  </div>
                </>
              )}

              {/* Physical */}
              {(physical?.gravity_m_s2 != null || cat?.magnetic_field_strength_ut != null) && (
                <Section title={t('info.sectionPhysical')} />
              )}
              <div className="space-y-0.5">
                <InfoRow
                  label={t('info.gravity')}
                  value={physical?.gravity_m_s2 != null
                    ? `${sig(physical.gravity_m_s2)} m/s² (${sig(physical.gravity_m_s2 / 9.81)} g)`
                    : undefined}
                />
                <InfoRow label={t('info.magneticField')} value={cat?.magnetic_field_strength_ut != null ? `${sig(cat.magnetic_field_strength_ut)} µT` : undefined} />
              </div>

              {/* Rotation & seasons */}
              {(planet.rotation_period_days != null || derived != null) && (
                <Section title={t('info.sectionRotation')} />
              )}
              <div className="space-y-0.5">
                <InfoRow label={t('info.rotationPeriod')} value={fmtDuration(planet.rotation_period_days ?? physical?.rotation_period_days)} />
                <InfoRow label={t('info.tidallyLocked')} value={derived?.tidally_locked != null ? (derived.tidally_locked ? '✓' : '—') : undefined} />
                <InfoRow label={t('info.solarDay')} value={fmtDuration(derived?.solar_day_days ?? undefined)} />
                <InfoRow label={t('info.axialTilt')} value={planet.axial_tilt_deg != null ? `${planet.axial_tilt_deg}°` : undefined} />
                <InfoRow label={t('info.daysPerYear')} value={derived?.days_per_year != null ? sig(derived.days_per_year, 4) : undefined} />
                <InfoRow label={t('info.seasonLength')} value={fmtDuration(derived?.season_length_days ?? undefined)} />
                <InfoRow label={t('info.polarCircle')} value={derived?.polar_circle_latitude_deg != null ? `${sig(derived.polar_circle_latitude_deg)}°` : undefined} />
              </div>

              {/* Atmosphere & hydrosphere */}
              {(cat?.atmosphere != null || cat?.hydrosphere != null) && (
                <Section title={t('info.sectionAtmo')} />
              )}
              <div className="space-y-0.5">
                <InfoRow label={t('info.surfacePressure')} value={cat?.atmosphere?.surface_pressure_atm != null ? `${sig(cat.atmosphere.surface_pressure_atm)} atm` : undefined} />
                <InfoRow label={t('info.greenhouse')} value={cat?.atmosphere?.greenhouse_factor != null ? `+${sig(cat.atmosphere.greenhouse_factor)} K` : undefined} />
                <InfoRow label={t('info.atmoComposition')} value={composition} />
                <InfoRow label={t('info.hydrosphere')} value={cat?.hydrosphere?.water_coverage != null ? `${Math.round(cat.hydrosphere.water_coverage * 100)}%` : undefined} />
                <InfoRow label={t('info.salinity')} value={cat?.hydrosphere?.salinity_ppt != null ? `${sig(cat.hydrosphere.salinity_ppt)} ppt` : undefined} />
                <InfoRow label={t('info.oceanDepth')} value={cat?.hydrosphere?.ocean_depth_km != null ? `${sig(cat.hydrosphere.ocean_depth_km)} km` : undefined} />
              </div>

              {/* Insolation & thermal */}
              {derived != null && <Section title={t('info.sectionThermal')} />}
              <div className="space-y-0.5">
                <InfoRow
                  label={t('info.instellation')}
                  value={derived?.instellation_w_m2 != null
                    ? `${sig(derived.instellation_w_m2, 4)} W/m²${derived.instellation_earth_ratio != null ? ` (${sig(derived.instellation_earth_ratio)}×)` : ''}`
                    : undefined}
                />
                <InfoRow label={t('info.equilibriumTemp')} value={derived?.equilibrium_temperature_k != null ? `${sig(derived.equilibrium_temperature_k)} K` : undefined} />
                <InfoRow label={t('info.inHabitableZone')} value={derived?.in_conservative_habitable_zone != null ? (derived.in_conservative_habitable_zone ? '✓' : '—') : undefined} />
              </div>

              {/* Lithosphere */}
              {cat?.lithosphere != null && <Section title={t('info.sectionLitho')} />}
              <div className="space-y-0.5">
                <InfoRow label={t('info.plateTectonics')} value={cat?.lithosphere?.has_plate_tectonics != null ? (cat.lithosphere.has_plate_tectonics ? '✓' : '—') : undefined} />
                <InfoRow label={t('info.numPlates')} value={cat?.lithosphere?.num_plates} />
                <InfoRow label={t('info.volcanicActivity')} value={cat?.lithosphere?.volcanic_activity != null ? `${sig(cat.lithosphere.volcanic_activity)}×` : undefined} />
              </div>

              {/* Terrain summary (collapsible, when CVT mesh data is available) */}
              {cvtMesh?.cells && cvtMesh.cells.length > 0 && (() => {
                const cells = cvtMesh.cells
                const totalCells = cells.length
                let landArea = 0
                let oceanArea = 0
                let continentalArea = 0
                let elevMin = Infinity
                let elevMax = -Infinity
                const plateIds = new Set<string>()

                for (const c of cells) {
                  const area = c.area_km2 ?? 0
                  if (c.water_class != null ? c.water_class === 'land' : c.elevation > 0) landArea += area
                  else oceanArea += area
                  if (c.crust_type === 'continental') continentalArea += area
                  if (c.elevation < elevMin) elevMin = c.elevation
                  if (c.elevation > elevMax) elevMax = c.elevation
                  if (c.plate_id) plateIds.add(c.plate_id)
                }
                if (!isFinite(elevMin)) elevMin = 0
                if (!isFinite(elevMax)) elevMax = 0

                const totalArea = landArea + oceanArea
                const landPct = totalArea > 0 ? (landArea / totalArea * 100).toFixed(1) : '0'
                const seaPct = totalArea > 0 ? (oceanArea / totalArea * 100).toFixed(1) : '0'
                const crustPct = totalArea > 0 ? (continentalArea / totalArea * 100).toFixed(1) : '0'
                const seaLevel = 0
                const peakProminence = elevMax - seaLevel
                const maxOceanDepth = seaLevel - elevMin

                const fmtKm2 = (km2: number) =>
                  km2 > 1_000_000
                    ? `${(km2 / 1_000_000).toFixed(1)}M km²`
                    : `${km2.toLocaleString(undefined, { maximumFractionDigits: 0 })} km²`

                return (
                  <div className="mt-2 pt-2 border-t border-space-border">
                    <button
                      onClick={() => setTerrainOpen((v) => !v)}
                      className="flex items-center gap-1 text-xs text-gray-500 font-semibold hover:text-neon-cyan transition-colors w-full text-left"
                    >
                      <span className="font-mono text-[10px]">{terrainOpen ? '▾' : '▸'}</span>
                      {t('info.terrain')}
                    </button>
                    {terrainOpen && (
                      <div className="mt-1 space-y-0">
                        <InfoRow label={t('info.landSeaRatio')} value={`${landPct}% / ${seaPct}%`} />
                        <InfoRow label={t('info.landArea')} value={fmtKm2(landArea)} />
                        <InfoRow label={t('info.oceanArea')} value={fmtKm2(oceanArea)} />
                        <InfoRow label={t('info.crustRatio')} value={`${crustPct}% / ${(100 - Number(crustPct)).toFixed(1)}%`} />
                        <InfoRow label={t('info.elevationRange')} value={`${Math.round(elevMin)} ~ ${Math.round(elevMax)} m`} />
                        <InfoRow label={t('info.highestPoint')} value={`${Math.round(peakProminence)} m`} />
                        <InfoRow label={t('info.deepestSea')} value={`${Math.round(maxOceanDepth)} m`} />
                        <InfoRow label={t('info.plateCount')} value={plateIds.size} />
                        <InfoRow label={t('info.cellCount')} value={totalCells.toLocaleString()} />
                        <InfoRow label="Seed" value={cvtMesh.seed} />
                      </div>
                    )}
                  </div>
                )
              })()}
            </>
          )
        })()}

        {/* ID */}
        <div className="mt-2 pt-2 border-t border-space-border">
          <span className="text-xs text-gray-600 font-mono">{selected.data.id}</span>
        </div>
      </div>
    </div>
  )
}

export type { SelectedBody }
