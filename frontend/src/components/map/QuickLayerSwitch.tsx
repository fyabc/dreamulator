import { useTranslation } from 'react-i18next'
import type { LayerState } from './MapLayerPanel'
import { LAYER_HELP } from './helpContent'
import { activeMainLayerId } from './layerStateInit'
import type { ColorMode } from '../../viewers/map/types'

const QUICK_LAYERS = ['terrain', 'temperature', 'precipitation', 'koppen'] as const

/**
 * Compact switcher for the four most-used thematic layers, placed in the map
 * toolbar next to the 2D/3D switch.  Applies the same single-slot rule as the
 * layer panel: selecting a thematic turns the other thematics off.
 */
export default function QuickLayerSwitch({ state, onChange, available, disabled = false }: {
  state: LayerState
  onChange: (state: LayerState) => void
  available?: ReadonlySet<ColorMode>
  disabled?: boolean
}) {
  const { t } = useTranslation('map')
  const active = activeMainLayerId(state)
  const select = (id: (typeof QUICK_LAYERS)[number]) => {
    if (disabled) return
    const entry = LAYER_HELP.find(layer => layer.id === id)
    const next: Record<ColorMode, number> = { ...state.layers }
    for (const other of LAYER_HELP) {
      if (other.kind === 'thematic') next[other.id] = 0
    }
    next[id] = entry?.defaultOpacity && entry.defaultOpacity > 0 ? entry.defaultOpacity : 0.85
    onChange({ layers: next, inspectedLayer: id })
  }
  return <nav aria-label={t('workbench.quickLayers')}
    className="inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap rounded border border-space-border bg-space-bg p-0.5">
    {QUICK_LAYERS.map(id => {
      const enabled = !disabled && (!available || available.has(id))
      const current = active === id
      return <button key={id} type="button" disabled={!enabled} aria-pressed={current}
        title={t(`help:layer.${id}.label`)}
        onClick={() => select(id)}
        className={`min-h-9 rounded px-2.5 text-sm transition-colors disabled:opacity-40 ${current
          ? 'bg-space-surface font-semibold text-gray-100 ring-1 ring-inset ring-neon-cyan/30' : 'text-gray-300 hover:bg-space-surface'}`}>
        {t(`workbench.quick.${id}`)}
      </button>
    })}
  </nav>
}
