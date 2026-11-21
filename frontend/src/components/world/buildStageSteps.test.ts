import { describe, expect, it } from 'vitest'
import type { BuildStage, BuildStep } from '../../api/buildJobs'
import { buildStageSteps } from './buildStageSteps'

const stage: BuildStage = {
  engine: 'climate', layer: 'climate', state: 'pending', bootstrap: false,
  started_at: null, finished_at: null, errors: [],
  planned_steps: ['reading', 'temperature', 'precipitation', 'koppen'],
}

const step = (name: string, finished: boolean, passNumber: number | null = null): BuildStep => ({
  name, started_at: '2026-01-01T00:00:00Z', finished_at: finished ? '2026-01-01T00:00:01Z' : null,
  completed: null, total: null, pass_number: passNumber,
})

describe('buildStageSteps', () => {
  it('previews planned work but does not show internal progress for a cache hit', () => {
    expect(buildStageSteps(stage).map(row => [row.name, row.state]))
      .toEqual(stage.planned_steps?.map(name => [name, 'pending']))
    expect(buildStageSteps({ ...stage, state: 'skipped' })).toEqual([])
  })

  it('keeps repeated moisture passes separate and leaves unobserved steps incomplete', () => {
    const rows = buildStageSteps({ ...stage, state: 'running', steps: [
      step('reading', true), step('precipitation', true, 1), step('precipitation', false, 2),
    ] })
    expect(rows.map(row => [row.id, row.state])).toEqual([
      ['reading:0', 'done'], ['temperature:0', 'not_run'],
      ['precipitation:0', 'done'], ['precipitation:1', 'active'], ['koppen:0', 'pending'],
    ])
    expect(rows.filter(row => row.name === 'precipitation').map(row => row.step?.pass_number)).toEqual([1, 2])
  })

  it('marks the last observed step as failed and does not complete later planned work', () => {
    const rows = buildStageSteps({ ...stage, state: 'failed', steps: [step('reading', true), step('temperature', true)] })
    expect(rows.map(row => row.state)).toEqual(['done', 'failed', 'not_run', 'not_run'])
  })
})
