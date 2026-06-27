/**
 * InfoPanel — HTML overlay showing details of the selected star or planet.
 */

import type { StarData } from './StarMesh'
import type { PlanetData } from './PlanetMesh'
import { formatRadius, formatMass } from './utils/scale'

type SelectedBody =
  | { type: 'star'; data: StarData }
  | { type: 'planet'; data: PlanetData }
  | null

interface InfoPanelProps {
  selected: SelectedBody
  onClose: () => void
}

const PLANET_TYPE_LABELS: Record<string, string> = {
  terrestrial: '类地行星',
  gas_giant: '气态巨行星',
  ice_giant: '冰巨行星',
  ocean_world: '海洋世界',
  dwarf: '矮行星',
}

function InfoRow({ label, value }: { label: string; value: string | number | undefined }) {
  if (value == null) return null
  return (
    <div className="flex justify-between gap-4 text-sm py-0.5">
      <span className="text-gray-500">{label}</span>
      <span className="text-gray-200 font-mono text-right">{value}</span>
    </div>
  )
}

export default function InfoPanel({ selected, onClose }: InfoPanelProps) {
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
              {selected.type === 'star' ? '恒星' : '行星'}
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
              <InfoRow label="光谱类型" value={`${star.spectral_class ?? 'N/A'} ${star.luminosity_class ?? ''}`} />
              <InfoRow label="温度" value={temp != null ? `${Math.round(temp)} K` : undefined} />
              <InfoRow label="半径" value={radius != null ? `${radius.toFixed(3)} R☉` : undefined} />
              <InfoRow label="光度" value={lum != null ? `${lum.toFixed(4)} L☉` : undefined} />
              <InfoRow label="质量" value={star.mass != null ? `${star.mass.toFixed(3)} M☉` : undefined} />
            </div>
          )
        })()}

        {/* Planet details */}
        {selected.type === 'planet' && (() => {
          const planet = selected.data
          const typeLabel = PLANET_TYPE_LABELS[planet.planet_type ?? ''] ?? planet.planet_type ?? 'N/A'
          return (
            <div className="space-y-0.5">
              <InfoRow label="类型" value={typeLabel} />
              <InfoRow label="质量" value={formatMass(planet.mass)} />
              <InfoRow label="半径" value={formatRadius(planet.radius)} />
              <InfoRow label="反照率" value={planet.albedo} />
              <InfoRow label="轴倾角" value={planet.axial_tilt_deg != null ? `${planet.axial_tilt_deg}°` : undefined} />
              <InfoRow label="自转周期" value={planet.rotation_period_days != null ? `${planet.rotation_period_days} 天` : undefined} />
              {planet.atmosphere && (
                <InfoRow label="大气压" value={`${planet.atmosphere.surface_pressure_atm ?? 1} atm`} />
              )}
              {planet.hydrosphere && (
                <InfoRow label="水覆盖率" value={`${Math.round((planet.hydrosphere.water_coverage ?? 0) * 100)}%`} />
              )}
            </div>
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
