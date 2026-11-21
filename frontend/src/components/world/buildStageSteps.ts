import type { BuildStage, BuildStep } from '../../api/buildJobs'

export interface StageStepRow {
  id: string
  name: string
  step?: BuildStep
  state: 'pending' | 'active' | 'done' | 'failed' | 'not_run'
}

export function buildStageSteps(stage: BuildStage): StageStepRow[] {
  if (stage.state === 'skipped') return []
  const observed = stage.steps ?? []
  const names = Array.from(new Set([...(stage.planned_steps ?? []), ...observed.map(step => step.name)]))
  const final = observed[observed.length - 1]
  const lastIndex = final ? names.indexOf(final.name) : -1
  const terminal = stage.state === 'succeeded' || stage.state === 'failed' || stage.state === 'not_run'
  return names.flatMap((name, index): StageStepRow[] => {
    const matches = observed.filter(step => step.name === name)
    if (!matches.length) return [{ id: `${name}:0`, name, state: terminal || index < lastIndex ? 'not_run' : 'pending' }]
    return matches.map((step, occurrence) => ({
      id: `${name}:${occurrence}`, name, step,
      state: step === final && stage.state === 'failed' ? 'failed' : step.finished_at == null ? 'active' : 'done',
    }))
  })
}
