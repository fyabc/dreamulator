/* eslint-disable react-refresh/only-export-components -- LAYER_ORDER/LAYER_LABELS are shared constants */
import { useTranslation } from 'react-i18next'
/**
 * LayerDag — canonical layer-order visualisation with build-status indicators.
 *
 * Status comes from the backend-enriched layer summary (world_layer_status):
 * `derived_fresh` (fresh / stale / absent) drives the indicator colour and
 * label, with the doc count / inheritance source / last build time as
 * secondary badges. The hand-maintained `configured` flag only serves as a
 * legacy fallback when the freshness fields are absent (old static exports).
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

export interface LayerDagEntry {
  configured?: boolean
  engine?: string
  /** Where the layer input resolves from ('root' | 'branch:<name>' | null). */
  input_source?: string | null
  /** Number of authored *.md documents. */
  input_doc_count?: number
  /** Build freshness: 'fresh' | 'stale' | 'absent'. */
  derived_fresh?: string
  /** ISO timestamp of the newest derived product. */
  last_build_time?: string | null
}

export interface LayerDagProps {
  layers: Record<string, LayerDagEntry>
  forkLayer?: string | null
  /** Extra note below the title, e.g. branch fork info. */
  note?: string
}

/** Compact relative time ("3 小时前" / "2 天前"); falls back to the date. */
function formatRelativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return iso
  const diffMs = Date.now() - then
  const minutes = Math.floor(diffMs / 60_000)
  if (minutes < 1) return '<1m'
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months}mo`
  return `${Math.floor(months / 12)}y`
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

          // Freshness drives the status dot; fall back to the legacy
          // configured flag when the enriched fields are absent.
          const fresh: string = info?.derived_fresh ?? (configured ? 'fresh' : 'absent')
          const hasData = fresh !== 'absent'
          const dotColor =
            fresh === 'fresh'
              ? 'bg-neon-cyan shadow-[0_0_6px_rgba(0,212,255,0.6)]'
              : fresh === 'stale'
                ? 'bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,0.5)]'
                : 'bg-gray-600'
          const statusLabel = !hasData
            ? t('layerDag.absent')
            : fresh === 'stale'
              ? t('layerDag.stale')
              : isForkedLayer
                ? t('layerDag.branchData')
                : t('layerDag.fresh')

          // Secondary badges: branch inheritance + doc count + build age.
          const inherits =
            info?.input_source && info.input_source.startsWith('branch:')
              ? info.input_source.slice('branch:'.length)
              : null
          const docs = info?.input_doc_count ?? 0
          const buildAge = info?.last_build_time
            ? formatRelativeTime(info.last_build_time)
            : null

          return (
            <div key={layer}>
              {/* Layer card */}
              <div
                className={`flex items-center gap-4 p-3 rounded-lg transition-colors ${
                  hasData
                    ? 'bg-space-surface/60 border border-neon-cyan/10'
                    : 'bg-space-bg/40 border border-transparent'
                } ${isForkedLayer ? 'border-l-2 border-l-neon-cyan/50' : ''}`}
              >
                {/* Status indicator */}
                <div className="flex-shrink-0">
                  <div className={`w-3 h-3 rounded-full ${dotColor}`} />
                </div>

                {/* Layer name + secondary badges */}
                <div className="flex-1 min-w-0 flex items-center gap-2 flex-wrap">
                  <span className={`font-medium ${hasData ? 'text-white' : 'text-gray-500'}`}>
                    {t(LAYER_LABELS[layer] ?? layer)}
                  </span>
                  <span className="text-gray-600 text-sm">{layer}</span>
                  {inherits && (
                    <span
                      className="text-xs px-1.5 py-0.5 rounded bg-space-surface text-gray-400 border border-space-border"
                      title={t('layerDag.inheritedFrom')}
                    >
                      ↳ {inherits}
                    </span>
                  )}
                  {docs > 0 && (
                    <span className="text-xs text-gray-500">
                      {t('layerDag.docCount', { count: docs })}
                    </span>
                  )}
                  {buildAge && (
                    <span className="text-xs text-gray-600" title={info?.last_build_time ?? ''}>
                      · {t('layerDag.buildAge', { age: buildAge })}
                    </span>
                  )}
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
                    fresh === 'stale'
                      ? 'text-amber-400/80'
                      : hasData
                        ? 'text-neon-cyan/70'
                        : 'text-gray-600'
                  }`}
                >
                  {statusLabel}
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
