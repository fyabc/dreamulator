import { Fragment } from 'react'
import { useTranslation } from 'react-i18next'
import AtlasIcon from '../AtlasIcon'
import type { BuildJob, BuildPlan } from '../../api/buildJobs'
import { layerIcon, layerNodeState, type LayerNodeState } from './layerStripState'

const NODE_CLASS: Record<LayerNodeState, string> = {
  fresh: 'border-emerald-700/50 bg-emerald-900/20 text-emerald-300/70',
  stale: 'border-amber-300/60 bg-amber-400/10 text-amber-200',
  absent: 'border-space-border bg-space-surface text-slate-500',
  upstream: 'border-amber-300/35 bg-transparent text-amber-200/60',
  pending: 'border-dashed border-amber-300/40 text-amber-200/60',
  running: 'border-neon-cyan bg-neon-cyan/10 text-neon-cyan motion-safe:animate-pulse',
  succeeded: 'border-emerald-500/60 bg-emerald-500/15 text-emerald-300',
  failed: 'border-red-400/60 bg-red-500/15 text-red-300',
  not_run: 'border-dashed border-space-border text-slate-600 opacity-60',
}

const BADGE: Partial<Record<LayerNodeState, string>> = {
  upstream: '↑',
  succeeded: '✓',
  failed: '×',
}

function connectorClass(next: LayerNodeState): string {
  switch (next) {
    case 'stale':
    case 'pending':
      return 'bg-amber-300/50'
    case 'upstream':
      return 'bg-amber-300/25'
    case 'running':
      return 'bg-neon-cyan/60'
    case 'succeeded':
      return 'bg-emerald-600/50'
    case 'failed':
      return 'bg-red-500/50'
    default:
      return 'bg-space-border'
  }
}

interface Props {
  plan: BuildPlan
  job: BuildJob | null
  active: boolean
  open: boolean
  onToggle: () => void
}

/**
 * Compact layer strip for the build plan: one node per engine layer in DAG
 * order, colored by freshness or, during a build, by execution state. The
 * whole strip opens the detailed plan popover.
 */
export default function MapBuildStrip({ plan, job, active, open, onToggle }: Props) {
  const { t } = useTranslation('map')
  const label = (name: string) => t(`worlds:layer.${name}`)
  const recompute = new Set(plan.recompute)
  const pending = plan.start_layer ? plan.recompute.length : 0
  const done = job?.stages.filter(stage => stage.state === 'succeeded' || stage.state === 'skipped').length ?? 0
  const total = job?.stages.length ?? 0
  const nodes = plan.layers.map(layer => ({
    layer,
    state: layerNodeState(layer, { active, recompute, job }),
  }))
  const summary = active
    ? `${done}/${total || '…'}`
    : pending ? t('buildPlan.count', { count: pending }) : ''
  const aria = active
    ? t('buildPlan.ariaBuilding', { done, total: total || '…' })
    : pending
      ? t('buildPlan.ariaPending', {
          count: pending,
          layers: plan.recompute.map(label).join(t('buildPlan.listSeparator')),
        })
      : t('buildPlan.fresh')

  return (
    <button type="button" aria-expanded={open} aria-label={aria} title={t('buildPlan.title')}
      onClick={onToggle}
      className="inline-flex items-center gap-1 whitespace-nowrap rounded border border-space-border bg-space-surface px-1.5 py-1 text-xs hover:border-neon-cyan/60 focus-visible:outline focus-visible:outline-neon-cyan">
      <span aria-hidden="true" className="flex items-center">
        {nodes.length === 0 && <span className="px-1 text-[10px] text-slate-400">{t('buildPlan.fresh')}</span>}
        {nodes.map(({ layer, state }, index) => (
          <Fragment key={layer.name}>
            {index > 0 && <span className={`h-px w-1.5 shrink-0 ${connectorClass(state)}`} />}
            <span title={`${label(layer.name)} · ${t(`buildPlan.state.${state}`)}`}
              data-layer={layer.name} data-state={state}
              className={`relative flex size-5 shrink-0 items-center justify-center rounded-full border ${NODE_CLASS[state]}`}>
              <AtlasIcon name={layerIcon(layer.name)} className="size-3" />
              {BADGE[state] && (
                <span className="absolute -right-0.5 -top-0.5 text-[8px] leading-none">{BADGE[state]}</span>
              )}
            </span>
          </Fragment>
        ))}
      </span>
      {summary && <span className="tabular-nums text-[10px] text-slate-400">{summary}</span>}
      <span aria-hidden="true" className="text-[9px] text-slate-500">{open ? '▴' : '▾'}</span>
    </button>
  )
}
