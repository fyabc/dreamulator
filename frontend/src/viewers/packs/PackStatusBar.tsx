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
      <div className="flex min-h-7 items-center justify-between gap-2 px-2 py-1.5 text-xs text-gray-400 sm:px-3">
        <span className="[@media(pointer:coarse)]:hidden">{t('packs.hoverPrompt')}</span>
        <span className="hidden [@media(pointer:coarse)]:inline">{t('packs.entry.tapToProbe')}</span>
        <span className="shrink-0 font-mono">{window.extentKmX.toFixed(0)} × {window.extentKmY.toFixed(0)} km</span>
      </div>
    )
  }

  const km = lonLatToKm(hover, window)
  const fmtOffset = (v: number) => `${v >= 0 ? '+' : '−'}${Math.abs(v).toFixed(1)} km`

  return (
    <div className="flex min-h-7 items-center gap-2 px-2 py-1.5 font-mono text-xs text-gray-400 sm:gap-3 sm:px-3">
      <span className="text-neon-cyan">
        {hover.lon.toFixed(4)}°, {hover.lat.toFixed(4)}°
      </span>
      <span className="hidden whitespace-nowrap sm:inline">
        ΔE {fmtOffset(km.x)} · ΔN {fmtOffset(km.y)}
      </span>
      <span className="ml-auto hidden whitespace-nowrap text-gray-400 xl:inline">{t('packs.lockPoint')}</span>
    </div>
  )
}
