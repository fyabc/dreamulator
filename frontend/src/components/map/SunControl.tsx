/**
 * SunControl — directional lighting controls for the 3D globe.
 *
 * Two independent controls drive the sun direction:
 *   - Sun longitude (0–360°): the diurnal (daily) rotation — where the sun is
 *     overhead in longitude. 0° = noon on the prime meridian.
 *   - Season (0–360°): the annual (orbital) position. Together with the planet's
 *     axial tilt this sets the solar declination — the latitude where the sun is
 *     directly overhead — so the terminator tilts across the year (midnight sun /
 *     polar night at the poles). 0° = vernal equinox, 90° = N. summer solstice.
 */

import { useCallback } from 'react'

import { solarDeclinationDeg } from '../../viewers/utils/solar'

interface SunControlProps {
  sunLongitudeDeg: number
  onLongitudeChange: (deg: number) => void
  seasonDeg: number
  onSeasonChange: (deg: number) => void
  /** Axial tilt in degrees — sets the amplitude of the seasonal declination. */
  axialTiltDeg?: number
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

/** Format a solar declination as a subsolar latitude, e.g. "23.4°N". */
function formatDeclination(dec: number): string {
  const abs = Math.abs(dec)
  if (abs < 0.05) return '0°（赤道）'
  return `${abs.toFixed(1)}°${dec > 0 ? 'N' : 'S'}`
}

export default function SunControl({
  sunLongitudeDeg,
  onLongitudeChange,
  seasonDeg,
  onSeasonChange,
  axialTiltDeg = 0,
}: SunControlProps) {
  const handleLongitude = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => onLongitudeChange(parseInt(e.target.value)),
    [onLongitudeChange],
  )
  const handleSeason = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => onSeasonChange(parseInt(e.target.value)),
    [onSeasonChange],
  )

  const declination = solarDeclinationDeg(seasonDeg, axialTiltDeg)

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-1.5">
        <span className="text-amber-400/80">
          <SunIcon />
        </span>
        <span className="text-xs text-gray-400">光照</span>
        {axialTiltDeg !== 0 && (
          <span className="text-[10px] font-mono tabular-nums ml-auto text-gray-500">
            倾角 {axialTiltDeg}°
          </span>
        )}
      </div>

      {/* Time of day (sun longitude) */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-gray-500">时刻（周日）</span>
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
          className="w-full h-1 accent-amber-400 cursor-pointer"
          title="太阳直射经度（0° = 本初子午线正午）"
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
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-gray-500">季节（周年）</span>
          <span className="text-[10px] font-mono tabular-nums text-amber-300/80">
            直射 {formatDeclination(declination)}
          </span>
        </div>
        <input
          type="range"
          min="0"
          max="360"
          value={seasonDeg}
          onChange={handleSeason}
          className="w-full h-1 accent-amber-400 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
          disabled={axialTiltDeg === 0}
          title={
            axialTiltDeg === 0
              ? '该行星无地轴倾角，无季节变化'
              : '轨道位置（0° = 春分，90° = 北半球夏至）'
          }
        />
        <div className="flex justify-between text-[9px] text-gray-600">
          <span>春分</span>
          <span>夏至</span>
          <span>秋分</span>
          <span>冬至</span>
          <span>春分</span>
        </div>
      </div>
    </div>
  )
}
