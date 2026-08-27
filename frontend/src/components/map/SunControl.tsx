/**
 * SunControl — directional lighting controls for the globe / map.
 *
 * Two independent controls drive the sun direction:
 *   - Sun longitude (0–360°): the diurnal (daily) rotation — where the sun is
 *     overhead in longitude. 0° = noon on the prime meridian.
 *   - Season (0–360°): the annual (orbital) position. Together with the planet's
 *     axial tilt this sets the solar declination — the latitude where the sun is
 *     directly overhead — so the terminator tilts across the year (midnight sun /
 *     polar night at the poles). 0° = vernal equinox, 90° = N. summer solstice.
 *
 * On the 3D globe lighting is always on (a lit sphere always has a terminator).
 * On the 2D map the day/night overlay is optional — pass `enabled` /
 * `onEnabledChange` to render an on/off toggle; omit them for always-on.
 */

import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'

import { solarDeclinationDeg } from '../../viewers/utils/solar'

interface SunControlProps {
  sunLongitudeDeg: number
  onLongitudeChange: (deg: number) => void
  seasonDeg: number
  onSeasonChange: (deg: number) => void
  /** Axial tilt in degrees — sets the amplitude of the seasonal declination. */
  axialTiltDeg?: number
  /** When provided (2D map), renders an on/off toggle for the overlay. */
  enabled?: boolean
  onEnabledChange?: (enabled: boolean) => void
  /** Show the month readout (M1–M12, Phase 4 monthly climate) beside the season. */
  showMonth?: boolean
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
  seasonDeg,
  onSeasonChange,
  axialTiltDeg = 0,
  enabled = true,
  onEnabledChange,
  showMonth = false,
}: SunControlProps) {
  const { t } = useTranslation('map')

  /** Format a solar declination as a subsolar latitude, e.g. "23.4°N". */
  const formatDeclination = (dec: number): string => {
    const abs = Math.abs(dec)
    if (abs < 0.05) return `0°（${t('sun.equator')}）`
    return `${abs.toFixed(1)}°${dec > 0 ? 'N' : 'S'}`
  }

  // Month of year (0–11), derived from the season angle.  0° = vernal equinox
  // = month 0 (M1); 90° = summer solstice = month 3 (M4).
  const monthOfYear = Math.round(seasonDeg / 30) % 12

  const handleLongitude = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => onLongitudeChange(parseInt(e.target.value)),
    [onLongitudeChange],
  )
  const handleSeason = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => onSeasonChange(parseInt(e.target.value)),
    [onSeasonChange],
  )

  const declination = solarDeclinationDeg(seasonDeg, axialTiltDeg)
  const hasToggle = onEnabledChange != null
  // Sliders are active when the overlay is on (or always, if there's no toggle).
  const active = hasToggle ? enabled : true

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-1.5">
        <span className="text-amber-400/80">
          <SunIcon />
        </span>
        <span className="text-xs text-gray-400">{t('sun.title')}</span>
        {axialTiltDeg !== 0 && (
          <span
            className={`text-[10px] font-mono tabular-nums text-gray-500 ${hasToggle ? '' : 'ml-auto'}`}
          >
            {t('sun.tilt', { deg: axialTiltDeg })}
          </span>
        )}
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

        {/* Season (orbital position → solar declination) */}
        <div className="space-y-1 mt-3">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-gray-500">{t('sun.season')}</span>
            <span className="text-[10px] font-mono tabular-nums text-amber-300/80">
              {t('sun.declination', { declination: formatDeclination(declination) })}
              {showMonth && (
                <span className="ml-2">{t('sun.monthValue', { m: monthOfYear + 1 })}</span>
              )}
            </span>
          </div>
          <input
            type="range"
            min="0"
            max="360"
            value={seasonDeg}
            onChange={handleSeason}
            className="w-full h-1 accent-amber-400 cursor-pointer disabled:cursor-not-allowed"
            disabled={!active || axialTiltDeg === 0}
            title={
              axialTiltDeg === 0
                ? t('sun.noTiltHint')
                : t('sun.seasonTitle')
            }
          />
          <div className="flex justify-between text-[9px] text-gray-600">
            <span>{t('sun.springEquinox')}</span>
            <span>{t('sun.summerSolstice')}</span>
            <span>{t('sun.autumnEquinox')}</span>
            <span>{t('sun.winterSolstice')}</span>
            <span>{t('sun.springEquinox')}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
