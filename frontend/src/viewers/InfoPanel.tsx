/**
 * InfoPanel — HTML overlay showing details of the selected star or planet.
 */

import { Link } from 'react-router-dom'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { StarData } from './StarMesh'
import type { PlanetData } from './PlanetMesh'
import { formatRadius, formatMass } from './utils/scale'
import type { CVTMesh } from './map/types'

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

export default function InfoPanel({ selected, onClose, worldName, branchQS, mapPlanetIds, cvtMesh }: InfoPanelProps) {
  const { t } = useTranslation('map')
  const [terrainOpen, setTerrainOpen] = useState(false)

  if (!selected) return null

  return (
    <div
      className="absolute bottom-4 right-4 z-10 w-72"
      style={{ pointerEvents: 'auto' }}
    >
      <div className="glass-panel p-4">
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

        {/* Star details */}
        {selected.type === 'star' && (() => {
          const star = selected.data
          const temp = star.derived?.computed_temperature ?? star.temperature
          const radius = star.derived?.computed_radius ?? star.radius
          const lum = star.derived?.computed_luminosity ?? star.luminosity
          return (
            <div className="space-y-0.5">
              <InfoRow label={t('info.spectralType')} value={`${star.spectral_class ?? 'N/A'} ${star.luminosity_class ?? ''}`} />
              <InfoRow label={t('info.temperature')} value={temp != null ? `${Math.round(temp)} K` : undefined} />
              <InfoRow label={t('info.radius')} value={radius != null ? `${radius.toFixed(3)} R☉` : undefined} />
              <InfoRow label={t('info.luminosity')} value={lum != null ? `${lum.toFixed(4)} L☉` : undefined} />
              <InfoRow label={t('info.mass')} value={star.mass != null ? `${star.mass.toFixed(3)} M☉` : undefined} />
            </div>
          )
        })()}

        {/* Planet details */}
        {selected.type === 'planet' && (() => {
          const planet = selected.data
          const typeKey = planet.planet_type ? PLANET_TYPE_LABELS[planet.planet_type] : undefined
          const typeLabel = typeKey ? t(typeKey) : (planet.planet_type ?? 'N/A')
          return (
            <>
              <div className="space-y-0.5">
                <InfoRow label={t('info.type')} value={typeLabel} />
                <InfoRow label={t('info.mass')} value={formatMass(planet.mass)} />
                <InfoRow label={t('info.radius')} value={formatRadius(planet.radius)} />
                <InfoRow label={t('info.albedo')} value={planet.albedo} />
                <InfoRow label={t('info.axialTilt')} value={planet.axial_tilt_deg != null ? `${planet.axial_tilt_deg}°` : undefined} />
                <InfoRow label={t('info.rotationPeriod')} value={planet.rotation_period_days != null ? `${planet.rotation_period_days} ${t('unit.days')}` : undefined} />
                {planet.atmosphere && (
                  <InfoRow label={t('info.atmosphere')} value={`${planet.atmosphere.surface_pressure_atm ?? 1} atm`} />
                )}
                {planet.hydrosphere && (
                  <InfoRow label={t('info.hydrosphere')} value={`${Math.round((planet.hydrosphere.water_coverage ?? 0) * 100)}%`} />
                )}
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

        {/* Action buttons */}
        {selected.type === 'planet' && worldName && (
          <div className="mt-2 pt-2 border-t border-space-border flex gap-2">
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

        {/* ID */}
        <div className="mt-2 pt-2 border-t border-space-border">
          <span className="text-xs text-gray-600 font-mono">{selected.data.id}</span>
        </div>
      </div>
    </div>
  )
}

export type { SelectedBody }
