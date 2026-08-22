/* eslint-disable react-refresh/only-export-components -- LAYER_ORDER/LAYER_LABELS are shared constants */
import { useTranslation } from 'react-i18next'
/**
 * LayerDag — canonical layer-order visualisation with status indicators.
 *
 * Extracted from WorldInfo.tsx so both WorldInfo and WorldDetail can share it.
 */

/** Canonical layer order from the engine DAG. */
export const LAYER_ORDER = [
  'physics',
  'chemistry',
  'astronomy',
  'geological',
  'climate',
  'ecology',
  'civilization',
]

/** i18n keys for layer names (resolve with `t()` at the consumption site). */
export const LAYER_LABELS: Record<string, string> = {
  physics: 'layer.physics',
  chemistry: 'layer.chemistry',
  astronomy: 'layer.astronomy',
  geological: 'layer.geological',
  climate: 'layer.climate',
  ecology: 'layer.ecology',
  civilization: 'layer.civilization',
}

export interface LayerDagProps {
  layers: Record<string, { configured?: boolean; engine?: string }>
  forkLayer?: string | null
  /** Extra note below the title, e.g. branch fork info. */
  note?: string
}

export default function LayerDag({ layers, forkLayer, note }: LayerDagProps) {
  const { t } = useTranslation('worlds')
  const forkIdx = forkLayer ? LAYER_ORDER.indexOf(forkLayer) : -1

  return (
    <section className="glass-panel p-6">
      <h3 className="text-lg font-semibold text-neon-cyan neon-glow-subtle mb-4">
        {t('layerDag.title')}
      </h3>
      {note && <p className="text-sm text-gray-500 mb-6">{note}</p>}

      <div className="space-y-1">
        {LAYER_ORDER.map((layer, i) => {
          const info = layers[layer]
          const configured = info?.configured ?? false
          const engine = info?.engine || ''
          const isLast = i === LAYER_ORDER.length - 1
          const isForkedLayer = forkIdx >= 0 && i >= forkIdx

          return (
            <div key={layer}>
              {/* Layer card */}
              <div
                className={`flex items-center gap-4 p-3 rounded-lg transition-colors ${
                  configured
                    ? 'bg-space-surface/60 border border-neon-cyan/10'
                    : 'bg-space-bg/40 border border-transparent'
                } ${isForkedLayer ? 'border-l-2 border-l-neon-cyan/50' : ''}`}
              >
                {/* Status indicator */}
                <div className="flex-shrink-0">
                  <div
                    className={`w-3 h-3 rounded-full ${
                      configured
                        ? 'bg-neon-cyan shadow-[0_0_6px_rgba(0,212,255,0.6)]'
                        : 'bg-gray-600'
                    }`}
                  />
                </div>

                {/* Layer name */}
                <div className="flex-1 min-w-0">
                  <span
                    className={`font-medium ${
                      configured ? 'text-white' : 'text-gray-500'
                    }`}
                  >
                    {t(LAYER_LABELS[layer] ?? layer)}
                  </span>
                  <span className="text-gray-600 text-sm ml-2">{layer}</span>
                </div>

                {/* Engine badge */}
                {configured && engine && (
                  <span className="text-xs px-2 py-0.5 rounded bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/20">
                    {engine}
                  </span>
                )}

                {/* Fork badge */}
                {isForkedLayer && layer === forkLayer && (
                  <span className="text-xs px-2 py-0.5 rounded bg-yellow-500/15 text-yellow-400 border border-yellow-500/20">
                    {t('layerDag.forkPoint')}
                  </span>
                )}

                {/* Status label */}
                <span
                  className={`text-xs ${
                    configured ? 'text-neon-cyan/70' : 'text-gray-600'
                  }`}
                >
                  {configured
                    ? isForkedLayer
                      ? t('layerDag.branchData')
                      : t('layerDag.configured')
                    : t('layerDag.unconfigured')}
                </span>
              </div>

              {/* Connector arrow */}
              {!isLast && (
                <div className="flex justify-start pl-[5px] py-0.5">
                  <div className="w-px h-3 bg-space-border" />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
