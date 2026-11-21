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
      <div className="border-t border-space-border bg-space-panel/80 px-3 py-1.5 text-xs text-gray-400">
        <span className="[@media(pointer:coarse)]:hidden">{t('packs.hoverPrompt')}</span>
        <span className="hidden [@media(pointer:coarse)]:inline">{t('packs.entry.tapToProbe')}</span>
      </div>
    )
  }

  const km = lonLatToKm(hover, window)
  const fmtOffset = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)} km`

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-space-border bg-space-panel/80 px-3 py-1.5 font-mono text-xs text-gray-400">
      <span className="text-neon-cyan">
        {hover.lon.toFixed(4)}°, {hover.lat.toFixed(4)}°
      </span>
      <span>
        ΔE {fmtOffset(km.x)} · ΔN {fmtOffset(km.y)}
      </span>
      <span className="ml-auto hidden text-gray-400 lg:inline">{t('packs.clickToProbe')}</span>
    </div>
  )
}
