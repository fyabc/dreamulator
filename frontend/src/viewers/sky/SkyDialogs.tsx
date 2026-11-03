/** SkyDialogs — the two floating dialogs behind the left-edge toolbar:
 *  observation (observer / location / branch) and display (mode, grids,
 *  optional panels, legend).  Stellarium posture: dialogs open on demand,
 *  chrome stays while they are held open.
 */

import { useTranslation } from 'react-i18next'

import BranchSelector from '../../components/BranchSelector'
import SkyLegend from './SkyLegend'
import type { GridToggles } from './skyGrids'

const DIALOG_SHELL =
  'border border-space-border bg-space-panel/95 backdrop-blur rounded-lg p-3 space-y-3 shadow-xl'

export interface ObserverOption {
  id: string
  name: string
}

export interface SkyObserverDialogProps {
  observerOptions: ObserverOption[]
  observerId: string | null
  onSelectObserver: (id: string) => void
  lat: number
  lon: number
  onLat: (value: number) => void
  onLon: (value: number) => void
  worldName: string
  branch: string | null
  onSelectBranch: (branch: string | null) => void
  spinSource?: string | null
  solarDayDays: number | null
  onPointerEnter: () => void
  onPointerLeave: () => void
}

export function SkyObserverDialog({
  observerOptions,
  observerId,
  onSelectObserver,
  lat,
  lon,
  onLat,
  onLon,
  worldName,
  branch,
  onSelectBranch,
  spinSource,
  solarDayDays,
  onPointerEnter,
  onPointerLeave,
}: SkyObserverDialogProps) {
  const { t } = useTranslation('sky')
  return (
    <div
      className={`${DIALOG_SHELL} w-60`}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
    >
      <div className="text-xs font-semibold text-neon-cyan">{t('dialog.observer.title')}</div>
      <label className="block space-y-1">
        <span className="text-[11px] text-gray-500">{t('observer.label')}</span>
        <select
          value={observerId ?? ''}
          onChange={(e) => onSelectObserver(e.target.value)}
          className="w-full px-2 py-1 rounded bg-space-surface text-xs text-gray-300 border border-space-border"
        >
          {observerOptions.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
      </label>
      <div className="flex gap-2">
        <label className="flex-1 space-y-1">
          <span className="text-[11px] text-gray-500">{t('observer.lat')}</span>
          <input
            type="number"
            min={-90}
            max={90}
            step={0.1}
            value={lat}
            onChange={(e) => onLat(Number(e.target.value))}
            className="w-full px-2 py-1 rounded bg-space-surface text-xs text-gray-300 border border-space-border"
          />
        </label>
        <label className="flex-1 space-y-1">
          <span className="text-[11px] text-gray-500">{t('observer.lon')}</span>
          <input
            type="number"
            step={0.1}
            value={lon}
            onChange={(e) => onLon(Number(e.target.value))}
            className="w-full px-2 py-1 rounded bg-space-surface text-xs text-gray-300 border border-space-border"
          />
        </label>
      </div>
      <BranchSelector worldName={worldName} selectedBranch={branch} onSelect={onSelectBranch} compact />
      {(spinSource || solarDayDays !== null) && (
        <div className="text-[10px] text-gray-600 space-y-0.5 pt-1 border-t border-space-border">
          {spinSource && (
            <div>
              {t('observer.spinSource')}: {spinSource}
            </div>
          )}
          {solarDayDays !== null && (
            <div>
              {t('observer.solarDay')} {solarDayDays.toFixed(2)} d
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export type SkyPanel = 'below' | 'almanac'

export interface SkyDisplayDialogProps {
  mode: 'pan' | 'disc'
  onMode: (mode: 'pan' | 'disc') => void
  grids: GridToggles
  onGrids: (grids: GridToggles) => void
  backgroundOn: boolean
  onBackgroundOn: (on: boolean) => void
  /** The one open right-side panel, if any (radio behaviour). */
  activePanel: SkyPanel | null
  onSelectPanel: (panel: SkyPanel | null) => void
  onPointerEnter: () => void
  onPointerLeave: () => void
}

export function SkyDisplayDialog({
  mode,
  onMode,
  grids,
  onGrids,
  backgroundOn,
  onBackgroundOn,
  activePanel,
  onSelectPanel,
  onPointerEnter,
  onPointerLeave,
}: SkyDisplayDialogProps) {
  const { t } = useTranslation('sky')
  const gridRow = (key: keyof GridToggles, label: string, color: string) => (
    <label key={key} className="flex items-center gap-2 text-[11px] text-gray-400 cursor-pointer">
      <input
        type="checkbox"
        checked={grids[key]}
        onChange={(e) => onGrids({ ...grids, [key]: e.target.checked })}
        className="accent-neon-cyan"
      />
      <span className="w-2.5 h-0.5 inline-block rounded" style={{ backgroundColor: color }} />
      {label}
    </label>
  )
  return (
    <div
      className={`${DIALOG_SHELL} w-60`}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
    >
      <div className="text-xs font-semibold text-neon-cyan">{t('dialog.display.title')}</div>
      <div className="flex rounded-md overflow-hidden border border-space-border text-[11px]">
        {(['pan', 'disc'] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => onMode(m)}
            className={`flex-1 px-2 py-1 transition-colors ${
              mode === m ? 'bg-neon-cyan/15 text-neon-cyan' : 'bg-space-surface text-gray-500 hover:text-gray-300'
            }`}
          >
            {t(`mode.${m}`)}
          </button>
        ))}
      </div>
      <div className="space-y-1">
        <div className="text-[11px] text-gray-500">{t('dialog.display.grids')}</div>
        {gridRow('altAz', t('grids.altAz'), 'rgba(255,255,255,0.35)')}
        {gridRow('equatorial', t('grids.equatorial'), 'rgba(77,166,255,0.7)')}
        {gridRow('ecliptic', t('grids.ecliptic'), 'rgba(240,192,64,0.7)')}
      </div>
      <label className="flex items-center gap-2 text-[11px] text-gray-400 cursor-pointer">
        <input
          type="checkbox"
          checked={backgroundOn}
          onChange={(e) => onBackgroundOn(e.target.checked)}
          className="accent-neon-cyan"
        />
        {t('dialog.display.background')}
      </label>
      <div className="space-y-1">
        <div className="text-[11px] text-gray-500">{t('dialog.display.panels')}</div>
        <div className="flex gap-1.5">
          {(['almanac', 'below'] as const).map((panel) => (
            <button
              key={panel}
              type="button"
              onClick={() => onSelectPanel(activePanel === panel ? null : panel)}
              className={`flex-1 px-2 py-1 rounded-md border text-[11px] transition-colors ${
                activePanel === panel
                  ? 'bg-neon-cyan/15 border-neon-cyan/40 text-neon-cyan'
                  : 'bg-space-surface border-space-border text-gray-500 hover:text-gray-300'
              }`}
            >
              {t(`panels.${panel}`)}
            </button>
          ))}
        </div>
      </div>
      <div className="pt-2 border-t border-space-border">
        <SkyLegend variant="inline" />
      </div>
    </div>
  )
}
