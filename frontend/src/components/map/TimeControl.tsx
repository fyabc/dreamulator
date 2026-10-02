/**
 * TimeControl — the global time dimension for the map / globe.
 *
 * "Annual average ↔ Monthly" is a data mode that spans several layer groups
 * (climate group's temperature / precipitation / pressure, plus the overlay
 * group's wind field), so it lives here — above the layer tree — rather than
 * inside any single group.
 *
 * A single season slider plays two roles depending on the mode:
 *   - Monthly: selects the data month (12 stops; month index 0 = March, the
 *     vernal equinox), and the solar declination follows that month so lighting
 *     stays consistent with the displayed data (July = N. summer illumination).
 *   - Annual:  continuous 0–360°, affecting only solar declination (lighting).
 */

import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'

import { solarDeclinationDeg } from '../../viewers/utils/solar'

interface TimeControlProps {
  monthlyMode: boolean
  onMonthlyModeChange: (mode: boolean) => void
  seasonDeg: number
  onSeasonChange: (deg: number) => void
  /** Axial tilt in degrees — enables the declination readout (annual mode). */
  axialTiltDeg?: number
  /** Seasonal cycle playback (video materials): month stepper + speed. */
  playing?: boolean
  onPlayingChange?: (playing: boolean) => void
  /** Milliseconds per month step (1000 / 2000 / 5000). */
  monthMs?: number
  onMonthMsChange?: (ms: number) => void
  /** Continuously sweep the sun longitude (one revolution per model year). */
  sunSweep?: boolean
  onSunSweepChange?: (v: boolean) => void
}

/** Season-month index (0 = March vernal equinox) from the season angle. */
function seasonMonthIndex(seasonDeg: number): number {
  return ((Math.round(seasonDeg / 30) % 12) + 12) % 12
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

export default function TimeControl({
  monthlyMode,
  onMonthlyModeChange,
  seasonDeg,
  onSeasonChange,
  axialTiltDeg = 0,
  playing = false,
  onPlayingChange,
  monthMs = 2000,
  onMonthMsChange,
  sunSweep = false,
  onSunSweepChange,
}: TimeControlProps) {
  const { t } = useTranslation('map')

  // Month names in natural order, indexed by season-month (0 = March).
  const months = t('months', { returnObjects: true }) as unknown as string[]
  const monthName = months[seasonMonthIndex(seasonDeg)] ?? String(seasonMonthIndex(seasonDeg) + 1)

  const declination = solarDeclinationDeg(seasonDeg, axialTiltDeg)
  const formatDeclination = (dec: number): string => {
    const abs = Math.abs(dec)
    if (abs < 0.05) return `0°（${t('sun.equator')}）`
    return `${abs.toFixed(1)}°${dec > 0 ? 'N' : 'S'}`
  }

  const handleSeason = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => onSeasonChange(parseInt(e.target.value)),
    [onSeasonChange],
  )

  // Monthly: 12 stops (0..360°, step 30, wrapping back to March). Annual:
  // continuous with a full 0–360° sweep. Tick marks are identical (13).
  const step = monthlyMode ? 30 : 1
  const hasTilt = axialTiltDeg !== 0
  const disabled = !monthlyMode && !hasTilt

  // Tick labels: month names (Mar/Jun/Sep/Dec, wrapped) in monthly mode,
  // the four seasonal markers in annual mode.
  const tickLabels = monthlyMode
    ? [months[0], months[3], months[6], months[9], months[0]]
    : [t('sun.springEquinox'), t('sun.summerSolstice'), t('sun.autumnEquinox'), t('sun.winterSolstice'), t('sun.springEquinox')]

  return (
    <div className="space-y-2">
      {/* Header */}
      <div className="flex items-center gap-1.5">
        <span className="text-xs text-gray-400" title={t('time.titleHint')}>{t('time.title')}</span>
        <a
          href="/help#map-time"
          target="_blank"
          rel="noreferrer"
          className="p-0.5 text-gray-500 hover:text-neon-cyan"
          title={t('control.helpButton')}
        >
          <HelpIcon />
        </a>
      </div>

      {/* Annual ↔ Monthly segmented switch */}
      <div className="flex rounded-md overflow-hidden border border-gray-700 text-[11px]">
        <button
          type="button"
          onClick={() => onMonthlyModeChange(false)}
          title={t('time.annualHint')}
          className={`flex-1 py-1 px-2 transition-colors ${
            !monthlyMode ? 'bg-neon-cyan/20 text-gray-100' : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          {t('time.annual')}
        </button>
        <button
          type="button"
          onClick={() => onMonthlyModeChange(true)}
          title={t('time.monthlyHint')}
          className={`flex-1 py-1 px-2 transition-colors border-l border-gray-700 ${
            monthlyMode ? 'bg-neon-cyan/20 text-gray-100' : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          {t('time.monthly')}
        </button>
      </div>

      {/* Seasonal cycle playback (monthly mode only — annual has no monthly
          data to animate; the play button explains instead of silently
          switching modes and pulling a 20 MB file). */}
      {(onPlayingChange || onMonthMsChange) && (
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => onPlayingChange?.(!playing)}
            disabled={!monthlyMode}
            title={monthlyMode ? t('time.playHint') : t('time.playNeedsMonthly')}
            className={`w-7 h-7 shrink-0 rounded-md flex items-center justify-center text-xs border transition-colors ${
              playing
                ? 'bg-amber-400/20 text-amber-200 border-amber-400/40'
                : 'bg-space-surface text-gray-400 border-space-border hover:text-amber-200 hover:border-amber-400/30'
            } disabled:opacity-40 disabled:cursor-not-allowed`}
          >
            {playing ? '⏸' : '▶'}
          </button>
          <select
            value={monthMs}
            onChange={(e) => onMonthMsChange?.(parseInt(e.target.value))}
            disabled={!monthlyMode || !playing}
            title={t('time.playSpeed')}
            className="px-1 py-0.5 rounded bg-space-surface text-[10px] text-gray-400 border border-space-border disabled:opacity-40"
          >
            <option value={1000}>{t('time.speedFast')}</option>
            <option value={2000}>{t('time.speedNormal')}</option>
            <option value={5000}>{t('time.speedSlow')}</option>
          </select>
          <label
            className="flex items-center gap-1 text-[10px] text-gray-500 select-none cursor-pointer"
            title={t('time.sunSweepHint')}
          >
            <input
              type="checkbox"
              checked={sunSweep}
              onChange={(e) => onSunSweepChange?.(e.target.checked)}
              disabled={!monthlyMode || !playing}
              className="accent-amber-400 w-3 h-3"
            />
            {t('time.sunSweep')}
          </label>
        </div>
      )}

      {/* Season / month slider */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-gray-500">
            {monthlyMode ? t('time.monthLabel') : t('time.seasonLabel')}
          </span>
          <span className="text-[10px] font-mono tabular-nums text-amber-300/80">
            {monthlyMode
              ? monthName
              : t('sun.declination', { declination: formatDeclination(declination) })}
          </span>
        </div>
        <input
          type="range"
          min="0"
          max="360"
          step={step}
          value={seasonDeg}
          onChange={handleSeason}
          disabled={disabled}
          className="w-full h-1 accent-amber-400 cursor-pointer disabled:cursor-not-allowed"
          title={monthlyMode ? t('time.monthlyHint') : t('time.annualHint')}
        />
        <div className="flex justify-between items-end h-2 px-px">
          {Array.from({ length: 13 }).map((_, i) => (
            <div
              key={i}
              className={`w-px ${i % 3 === 0 ? 'h-2 bg-gray-500' : 'h-1 bg-gray-700'}`}
            />
          ))}
        </div>
        <div className="flex justify-between text-[9px] text-gray-600">
          {tickLabels.map((label, i) => (
            <span key={i}>{label}</span>
          ))}
        </div>
      </div>
    </div>
  )
}
