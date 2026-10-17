/**
 * PackStatusBar — hover readout for the pack viewer: exact lon/lat plus the
 * kilometre offset from the window centre, in the MapStatusBar style.
 */

import { useTranslation } from 'react-i18next'
import type { LonLat } from '../map/utils/mapCoords'
import { lonLatToKm, type PackWindow } from './packCoords'

interface PackStatusBarProps {
  hover: LonLat | null
  window: PackWindow
}

export default function PackStatusBar({ hover, window }: PackStatusBarProps) {
  const { t } = useTranslation('map')

  if (!hover) {
    return (
      <div className="flex items-center gap-4 px-3 py-1.5 bg-space-panel/80 border-t border-space-border text-xs text-gray-500 font-mono">
        <span>{t('packs.hoverPrompt')}</span>
      </div>
    )
  }

  const km = lonLatToKm(hover, window)
  const fmtOffset = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)} km`

  return (
    <div className="flex items-center gap-3 px-3 py-1.5 bg-space-panel/80 border-t border-space-border text-xs text-gray-400 font-mono">
      <span className="text-neon-cyan">
        {hover.lon.toFixed(4)}°, {hover.lat.toFixed(4)}°
      </span>
      <span className="text-gray-600">|</span>
      <span>
        ΔE {fmtOffset(km.x)} · ΔN {fmtOffset(km.y)}
      </span>
      <span className="ml-auto text-gray-600">{t('packs.clickToProbe')}</span>
    </div>
  )
}
