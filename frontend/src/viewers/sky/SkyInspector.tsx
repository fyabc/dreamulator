/** SkyInspector — the selected body's full field list (null-tolerant for
 *  fast-path rows and star rows).
 */

import { useTranslation } from 'react-i18next'

import { formatIrradiance } from './units'
import type { SkyEphemerisResult } from './types'

function fmtDistance(km: number): string {
  return km >= 1e7 ? `${(km / 149_597_870.7).toFixed(3)} AU` : `${Math.round(km).toLocaleString()} km`
}

function fmtAngleSize(deg: number): string {
  if (deg >= 0.1) return `${deg.toFixed(2)}°`
  const arcmin = deg * 60
  if (arcmin >= 1) return `${arcmin.toFixed(1)}′`
  return `${(deg * 3600).toFixed(1)}″`
}

export interface SkyInspectorProps {
  result: SkyEphemerisResult | undefined
  selectedId: string | null
}

export default function SkyInspector({ result, selectedId }: SkyInspectorProps) {
  const { t } = useTranslation('sky')
  if (!result || !selectedId) {
    return (
      <div className="text-[11px] text-gray-500 italic">{t('inspector.none')}</div>
    )
  }
  const row = result.targets.find((r) => r.body_id === selectedId)
  if (!row) {
    return <div className="text-[11px] text-gray-500 italic">{t('inspector.none')}</div>
  }
  const fields: Array<[string, string]> = [
    [t('inspector.phaseAngle'), row.phase_angle_deg !== null ? `${row.phase_angle_deg.toFixed(1)}°` : '—'],
    [
      t('inspector.illuminated'),
      row.illuminated_fraction !== null ? `${(row.illuminated_fraction * 100).toFixed(0)}%` : '—',
    ],
    [
      t('inspector.phaseFunction'),
      row.phase_function !== null ? row.phase_function.toFixed(3) : '—',
    ],
    [t('inspector.magnitude'), row.apparent_magnitude.toFixed(2)],
    [t('inspector.illuminance'), formatIrradiance(row.illuminance_w_m2)],
    [t('inspector.distance'), fmtDistance(row.distance_km)],
    [t('inspector.angularDiameter'), fmtAngleSize(row.angular_diameter_deg)],
    [t('inspector.altitudeRate'), `${row.altitude_rate_deg_per_hr >= 0 ? '+' : ''}${row.altitude_rate_deg_per_hr.toFixed(2)}°/h`],
    [t('inspector.elongationStar'), row.elongation_star_deg !== null ? `${row.elongation_star_deg.toFixed(1)}°` : '—'],
    [t('inspector.elongationParent'), row.elongation_parent_deg !== null ? `${row.elongation_parent_deg.toFixed(1)}°` : '—'],
    [t('inspector.ra'), `${row.equatorial_ra_deg.toFixed(1)}°`],
    [t('inspector.dec'), `${row.equatorial_dec_deg >= 0 ? '+' : ''}${row.equatorial_dec_deg.toFixed(1)}°`],
    [t('inspector.eclipticLon'), `${row.ecliptic_lon_deg.toFixed(1)}°`],
    [t('inspector.eclipticLat'), `${row.ecliptic_lat_deg >= 0 ? '+' : ''}${row.ecliptic_lat_deg.toFixed(1)}°`],
    [
      t('rise.state'),
      row.rise_state !== null
        ? t(`rise.${row.rise_state}`)
        : `— ${t('chart.noRiseInfo')}`,
    ],
    [t('rise.nextRise'), row.next_rise_days !== null ? `${row.next_rise_days.toFixed(2)} d` : '—'],
    [t('rise.nextSet'), row.next_set_days !== null ? `${row.next_set_days.toFixed(2)} d` : '—'],
  ]
  return (
    <div>
      <div className="text-sm font-semibold text-neon-cyan mb-2">
        {row.name ?? row.body_id}
      </div>
      <dl className="space-y-1">
        {fields.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-2 text-[11px]">
            <dt className="text-gray-500 shrink-0">{label}</dt>
            <dd className="font-mono tabular-nums text-gray-300 text-right">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
