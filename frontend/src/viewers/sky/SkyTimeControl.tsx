/** SkyTimeControl — the bottom-bar time control, one row: instant readout +
 *  clock + typed input + unit toggle on the left, play + log-scale speed
 *  slider (with decade ticks, in observer solar days per second — the dial's
 *  own unit, so speed and clock visibly agree) on the right. */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { dayClock, dayReadout } from './timeFormat'
import type { SkyTimeState } from './useSkyTime'

export interface SkyTimeControlProps {
  time: SkyTimeState
  solarDayDays: number | null
}

const SPEED_MIN = 0.01
const SPEED_MAX = 10
/** log10 range of the speed slider. */
const LOG_MIN = -2
const LOG_MAX = 1
const SPEED_TICKS = [0.01, 0.1, 1, 10]

export default function SkyTimeControl({ time, solarDayDays }: SkyTimeControlProps) {
  const { t } = useTranslation('sky')
  const hasSolar = solarDayDays !== null
  const [unit, setUnit] = useState<'solar' | 'earth'>('solar')
  const activeUnit = hasSolar ? unit : 'earth'
  const dayLen = activeUnit === 'solar' && hasSolar ? (solarDayDays as number) : 1

  const readout = dayReadout(time.atLive / dayLen, 1)
  const clock = dayClock(time.atLive / dayLen, 1)

  // Local editing buffer for the typed input: commits on Enter/blur.
  const [editDays, setEditDays] = useState<string | null>(null)
  const commitEdit = () => {
    if (editDays === null) return
    const value = Number(editDays)
    if (Number.isFinite(value)) time.setAt(value * dayLen)
    setEditDays(null)
  }

  const speed = time.playSpeedSolarDaysPerSec
  const speedSlider = Math.log10(Math.min(SPEED_MAX, Math.max(SPEED_MIN, speed)))

  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[11px] text-gray-400">
      {/* Left: instant readout + clock + typed input + unit toggle */}
      <div className="flex items-center gap-2 font-mono tabular-nums min-w-0" title={t('time.epochHint')}>
        <span className="whitespace-nowrap">
          {t('time.epochDays')} {readout.day}
          {t('time.day')} + {readout.fraction.toFixed(2)}
        </span>
        {clock !== null && <span className="text-gray-500">{clock}</span>}
        <input
          type="number"
          step={0.01}
          value={editDays ?? (time.atLive / dayLen).toFixed(2)}
          onChange={(e) => setEditDays(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
          }}
          className="w-20 px-1.5 py-0.5 rounded bg-space-surface text-[11px] text-gray-300 border border-space-border text-right"
          aria-label={t('time.epochDays')}
          title={t('time.inputHint')}
        />
        {hasSolar && (
          <button
            type="button"
            onClick={() => setUnit(activeUnit === 'solar' ? 'earth' : 'solar')}
            className="px-1.5 py-0.5 rounded bg-space-surface text-[10px] text-gray-500 border border-space-border hover:text-gray-300 whitespace-nowrap"
            title={t('time.unitHint')}
          >
            {t(activeUnit === 'solar' ? 'time.unitSolar' : 'time.unitEarth')}
          </button>
        )}
      </div>

      {/* Right: play + log speed slider with decade ticks.  When the bar
          wraps (narrow screens) this group spreads across its own full row
          instead of hugging the right edge of a second line. */}
      <div className="flex items-center gap-2 min-w-[11rem] flex-1 justify-between sm:justify-end">
        <button
          type="button"
          onClick={() => time.setPlaying(!time.playing)}
          title={time.playing ? t('time.pause') : t('time.play')}
          className={`w-7 h-7 shrink-0 rounded-md flex items-center justify-center text-xs border transition-colors ${
            time.playing
              ? 'bg-amber-400/20 text-amber-200 border-amber-400/40'
              : 'bg-space-surface text-gray-400 border-space-border hover:text-amber-200 hover:border-amber-400/30'
          }`}
        >
          {time.playing ? '⏸' : '▶'}
        </button>
        <div className="flex-1 max-w-[16rem]" title={t('time.speed')}>
          <input
            type="range"
            min={LOG_MIN}
            max={LOG_MAX}
            step={0.02}
            value={speedSlider}
            onChange={(e) => time.setPlaySpeed(Math.pow(10, Number(e.target.value)))}
            className="w-full accent-amber-400"
            aria-label={t('time.speed')}
          />
          <div className="relative h-3 -mt-1 text-[9px] text-gray-600 select-none">
            {SPEED_TICKS.map((tick) => (
              <span
                key={tick}
                className="absolute -translate-x-1/2 text-center leading-none"
                style={{ left: `${((Math.log10(tick) - LOG_MIN) / (LOG_MAX - LOG_MIN)) * 100}%` }}
              >
                <span className="block w-px h-1 bg-gray-700 mx-auto mb-0.5" />
                {tick}
              </span>
            ))}
          </div>
        </div>
        <span
          className="font-mono tabular-nums text-[10px] text-gray-500 whitespace-nowrap w-20 text-right"
          title={t('time.speedHint')}
        >
          {speed.toFixed(2)} {t(hasSolar ? 'time.speedUnitSolar' : 'time.speedUnitEarth')}
        </span>
      </div>
    </div>
  )
}
