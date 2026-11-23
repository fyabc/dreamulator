import { describe, expect, it } from 'vitest'
import type { BuildJob, BuildStage, LayerBuildState } from '../../api/buildJobs'
import { layerIcon, layerNodeState } from './layerStripState'

function layer(name: string, derived_fresh: string): LayerBuildState {
  return { name, derived_fresh, input_source: 'root', last_build_time: null }
}

function stage(layerName: string, state: BuildStage['state'], bootstrap = false): BuildStage {
  return {
    engine: layerName,
    layer: layerName,
    bootstrap,
    state,
    started_at: null,
    finished_at: null,
    errors: [],
  }
}

function job(stages: BuildStage[], state: BuildJob['state'] = 'running'): BuildJob {
  return {
    id: 'job-1',
    world: 'w',
    branch: null,
    engine: null,
    start_layer: null,
    force: false,
    state,
    created_at: '',
    started_at: null,
    updated_at: '',
    finished_at: null,
    elapsed_seconds: 0,
    current_engine: null,
    stages,
    result: null,
    error: null,
  }
}

const noJob = { active: false, recompute: new Set<string>(), job: null }

describe('layerNodeState', () => {
  it('uses the plan freshness when no build is running', () => {
    expect(layerNodeState(layer('climate', 'fresh'), noJob)).toBe('fresh')
    expect(layerNodeState(layer('climate', 'stale'), noJob)).toBe('stale')
    expect(layerNodeState(layer('climate', 'absent'), noJob)).toBe('absent')
    expect(layerNodeState(layer('climate', 'unexpected'), noJob)).toBe('absent')
  })

  it('lets execution stages override freshness while active', () => {
    const options = { active: true, recompute: new Set(['climate', 'ecology']), job: job([
      stage('climate', 'succeeded'),
      stage('ecology', 'running'),
    ]) }
    expect(layerNodeState(layer('climate', 'stale'), options)).toBe('succeeded')
    expect(layerNodeState(layer('ecology', 'stale'), options)).toBe('running')
    expect(layerNodeState(layer('civilization', 'stale'), options)).toBe('stale')
  })

  it('maps validating to running and skipped to succeeded', () => {
    const options = (state: BuildStage['state']) => ({
      active: true,
      recompute: new Set(['climate']),
      job: job([stage('climate', state)]),
    })
    expect(layerNodeState(layer('climate', 'stale'), options('validating'))).toBe('running')
    expect(layerNodeState(layer('climate', 'stale'), options('skipped'))).toBe('succeeded')
    expect(layerNodeState(layer('climate', 'stale'), options('failed'))).toBe('failed')
    expect(layerNodeState(layer('climate', 'stale'), options('not_run'))).toBe('not_run')
  })

  it('marks recompute layers without a stage yet as pending', () => {
    const options = { active: true, recompute: new Set(['climate', 'ecology']), job: job([]) }
    expect(layerNodeState(layer('climate', 'fresh'), options)).toBe('pending')
    expect(layerNodeState(layer('astronomy', 'fresh'), options)).toBe('fresh')
  })

  it('ignores bootstrap stages and finished jobs', () => {
    const bootstrap = { active: true, recompute: new Set<string>(), job: job([
      stage('climate', 'running', true),
    ]) }
    expect(layerNodeState(layer('climate', 'fresh'), bootstrap)).toBe('fresh')
    const finished = { active: false, recompute: new Set(['climate']), job: job([
      stage('climate', 'failed'),
    ], 'failed') }
    expect(layerNodeState(layer('climate', 'stale'), finished)).toBe('stale')
  })
})

describe('layerIcon', () => {
  it('has an icon per engine layer and a fallback', () => {
    expect(layerIcon('astronomy')).toBe('stars')
    expect(layerIcon('geological')).toBe('geology')
    expect(layerIcon('climate')).toBe('climate')
    expect(layerIcon('ecology')).toBe('leaf')
    expect(layerIcon('civilization')).toBe('temple')
    expect(layerIcon('future-layer')).toBe('layers')
  })
})
