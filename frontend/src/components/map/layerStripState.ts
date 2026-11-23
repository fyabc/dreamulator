import type { BuildJob, LayerBuildState } from '../../api/buildJobs'
import type { AtlasIconName } from '../AtlasIcon'

/** Visual state of one layer node in the build strip. */
export type LayerNodeState =
  | 'fresh'
  | 'stale'
  | 'absent'
  | 'upstream'
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'not_run'

const LAYER_ICONS: Record<string, AtlasIconName> = {
  astronomy: 'stars',
  geological: 'geology',
  climate: 'climate',
  ecology: 'leaf',
  civilization: 'temple',
}

export function layerIcon(name: string): AtlasIconName {
  return LAYER_ICONS[name] ?? 'layers'
}

const STAGE_STATES: Record<string, LayerNodeState> = {
  pending: 'pending',
  validating: 'running',
  running: 'running',
  succeeded: 'succeeded',
  skipped: 'succeeded',
  failed: 'failed',
  not_run: 'not_run',
}

function freshnessState(layer: LayerBuildState): LayerNodeState {
  return layer.derived_fresh === 'fresh' ||
    layer.derived_fresh === 'stale' ||
    layer.derived_fresh === 'absent'
    ? layer.derived_fresh
    : 'absent'
}

/**
 * Display state of a plan layer outside a build.
 *
 * A layer whose own derived data is fresh is still out of date when it sits
 * downstream of a changed layer: its results were computed from old upstream
 * inputs. ``recompute`` holds the earliest changed layer and everything after
 * it, so a fresh layer in that chain is marked ``upstream`` instead of
 * ``fresh``.
 */
export function planLayerState(
  layer: LayerBuildState,
  recompute: ReadonlySet<string>,
): LayerNodeState {
  const own = freshnessState(layer)
  if (own === 'fresh' && recompute.has(layer.name)) return 'upstream'
  return own
}

/**
 * Resolve the strip state of one plan layer.
 *
 * While a build is active, its execution stages take precedence over
 * freshness; layers outside the recompute chain keep their plan state.
 * Bootstrap stages belong to upstream preparation and never appear in the
 * strip, so they are ignored here.
 */
export function layerNodeState(
  layer: LayerBuildState,
  { active, recompute, job }: {
    active: boolean
    recompute: ReadonlySet<string>
    job?: BuildJob | null
  },
): LayerNodeState {
  if (active) {
    const stage = job?.stages.find(candidate => !candidate.bootstrap && candidate.layer === layer.name)
    if (stage) return STAGE_STATES[stage.state] ?? 'pending'
    if (recompute.has(layer.name)) return 'pending'
  }
  return planLayerState(layer, recompute)
}
