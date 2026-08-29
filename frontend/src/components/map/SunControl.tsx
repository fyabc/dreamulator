/**
 * SunControl — diurnal lighting controls for the globe / map.
 *
 * Controls only the daily (diurnal) sun longitude — where the sun is overhead
 * in longitude (0° = noon on the prime meridian). The seasonal / monthly
 * dimension (which drives both solar declination and monthly climate data) has
 * moved to TimeControl, so the two time axes are cleanly separated:
 *
 *   - SunControl  → daily rotation (sun longitude) + day/night toggle
 *   - TimeControl → annual season / monthly data month
 *
 * On the 3D globe lighting is always on. On the 2D map the day/night overlay is
 * optional — pass `enabled` / `onEnabledChange` to render an on/off toggle;
 * omit them for always-on.
 */

import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'

interface SunControlProps {
  sunLongitudeDeg: number
  onLongitudeChange: (deg: number) => void
  /** When provided (2D map), renders an on/off toggle for the overlay. */
  enabled?: boolean
  onEnabledChange?: (enabled: boolean) => void
}

/** Help-circle icon — links to the time/lighting help section. */
function HelpIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  )
}

/** Simple sun icon as inline SVG. */
function SunIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  )
}

export default function SunControl({
  sunLongitudeDeg,
  onLongitudeChange,
  enabled = true,
  onEnabledChange,
}: SunControlProps) {
  const { t } = useTranslation('map')

  const handleLongitude = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => onLongitudeChange(parseInt(e.target.value)),
    [onLongitudeChange],
  )

  const hasToggle = onEnabledChange != null
  const active = hasToggle ? enabled : true

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-1.5">
        <span className="text-amber-400/80">
          <SunIcon />
        </span>
        <span className="text-xs text-gray-400" title={t('sun.titleHint')}>{t('sun.title')}</span>
        <a
          href="/help#map-time"
          target="_blank"
          rel="noreferrer"
          className="p-0.5 text-gray-500 hover:text-neon-cyan"
          title={t('control.helpButton')}
        >
          <HelpIcon />
        </a>
        {hasToggle && (
          <button
            type="button"
            onClick={() => onEnabledChange?.(!enabled)}
            className={`ml-auto relative w-7 h-4 shrink-0 rounded-full transition-colors ${
              enabled ? 'bg-amber-400/80' : 'bg-gray-600'
            }`}
            title={enabled ? t('sun.toggleOff') : t('sun.toggleOn')}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white transition-transform ${
                enabled ? 'translate-x-3' : ''
              }`}
            />
          </button>
        )}
      </div>

      <div className={active ? '' : 'opacity-40'}>
        {/* Time of day (sun longitude) */}
        <div className="space-y-1">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-gray-500">{t('sun.timeOfDay')}</span>
            <span className="text-[10px] font-mono tabular-nums text-amber-300/80">
              {sunLongitudeDeg}°
            </span>
          </div>
          <input
            type="range"
            min="0"
            max="360"
            value={sunLongitudeDeg}
            onChange={handleLongitude}
            disabled={!active}
            className="w-full h-1 accent-amber-400 cursor-pointer disabled:cursor-not-allowed"
            title={t('sun.longitudeTitle')}
          />
          <div className="flex justify-between text-[9px] text-gray-600 font-mono">
            <span>0°</span>
            <span>90°</span>
            <span>180°</span>
            <span>270°</span>
            <span>360°</span>
          </div>
        </div>
      </div>
    </div>
  )
}
