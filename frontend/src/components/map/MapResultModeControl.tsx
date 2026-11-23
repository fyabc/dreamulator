import { useTranslation } from 'react-i18next'
import type { MapMode } from '../../viewers/map/useTemperatureTrialPreview'
import HoverHelp from '../HoverHelp'

/**
 * Result source for the map: the official build or a development result.
 * Rendered into the global world/branch bar, so it applies to the whole map
 * rather than to one panel.
 */
export default function MapResultModeControl({ mode, onChange, ready }: {
  mode: MapMode
  onChange: (mode: MapMode) => void
  ready?: boolean
}) {
  const { t } = useTranslation('map')
  return (
    <div className="inline-flex shrink-0 items-center gap-1.5 text-xs text-slate-400">
      <label className="inline-flex items-center gap-1.5"
        title={t(mode === 'trial' ? 'workbench.developmentHint' : 'workbench.officialHint')}>
        <span className="hidden sm:inline">{t('workbench.resultMode')}</span>
        <select aria-label={t('workbench.resultMode')} value={mode}
          onChange={event => onChange(event.target.value === 'trial' ? 'trial' : 'official')}
          className="rounded border border-space-border bg-space-surface px-1.5 py-0.5 text-xs text-slate-100 hover:border-neon-cyan/50 focus-visible:outline focus-visible:outline-neon-cyan">
          <option value="official">{t('workbench.official')}</option>
          <option value="trial">{t('workbench.development')}</option>
        </select>
        {mode === 'trial' && <span className={`hidden whitespace-nowrap lg:inline ${ready === false ? 'text-slate-500' : 'text-amber-200/90'}`}>
          {t(ready === false ? 'workbench.developmentMissing' : 'workbench.developmentSource')}
        </span>}
      </label>
      <HoverHelp label={t('workbench.modeHelp')}>{t('workbench.modeHelp')}</HoverHelp>
    </div>
  )
}
