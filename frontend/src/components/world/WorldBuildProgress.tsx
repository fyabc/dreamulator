import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import type { BuildJob, BuildStage } from '../../api/buildJobs'
import ProgressTimeline, { type TimelineItem } from '../ProgressTimeline'
import { buildStageSteps } from './buildStageSteps'

const stateStyle: Record<BuildStage['state'], TimelineItem['state']> = {
  pending: 'pending', validating: 'active', running: 'active', succeeded: 'done',
  failed: 'failed', skipped: 'skipped', not_run: 'pending',
}

export default function WorldBuildProgress({ job, running }: { job: BuildJob; running: boolean }) {
  const { t, i18n } = useTranslation('worlds')
  const titleId = useId()
  const format = new Intl.NumberFormat(i18n.resolvedLanguage, { maximumFractionDigits: 1 })
  const snapshotTime = job.started_at ? Date.parse(job.started_at) + job.elapsed_seconds * 1000 : Date.parse(job.updated_at)
  const elapsed = (start: string, end: string | null) =>
    format.format(Math.max(0, ((end ? Date.parse(end) : snapshotTime) - Date.parse(start)) / 1000))
  let current: { id: string; layer: string; step?: string; done: number; total: number } | undefined
  const items: TimelineItem[] = []
  for (const stage of job.stages) {
    const id = `${stage.engine}:${stage.bootstrap}`
    const state = stateStyle[stage.state]
    const steps = buildStageSteps(stage)
    const label = t(`layer.${stage.layer}`, { defaultValue: stage.engine })
    const done = steps.filter(step => step.state === 'done').length
    if (state === 'active') current = { id, layer: label, done, total: steps.length }
    items.push({
      id, state,
      label: <span className="text-sm font-semibold">{label}{stage.bootstrap && <span className="ml-2 text-xs font-normal">{t('build.bootstrap')}</span>}</span>,
      status: steps.length ? t('build.layerStepCount', { done, total: steps.length, status: t(`build.stage.${stage.state}`) }) : t(`build.stage.${stage.state}`),
      detail: stage.errors.length > 0 && <ul className="list-disc break-words pl-4 text-red-300">
        {stage.errors.map((error, index) => <li key={index}>{error}</li>)}
      </ul>,
    }, ...steps.map((row): TimelineItem => {
      const stepId = `${id}:${row.id}`
      const step = row.step
      const stepLabel = row.name === 'precipitation' && step?.pass_number != null
        ? t('build.moisturePass', { pass: step.pass_number })
        : t(`build.step.${row.name}`, { defaultValue: row.name })
      if (row.state === 'active') current = { id: stepId, layer: label, step: stepLabel, done, total: steps.length }
      const completed = step?.completed
      const total = step?.total
      return {
        id: stepId, state: row.state === 'not_run' ? 'skipped' : row.state, substep: true,
        label: stepLabel,
        status: row.state === 'failed' ? t('build.stage.failed') : step
          ? t('build.stepElapsed', { seconds: elapsed(step.started_at, step.finished_at) }) : t(`build.stage.${row.state}`),
        detail: completed != null && total != null && <p>{t(`build.counter.${row.name}`, {
          done: format.format(completed), total: format.format(total),
          defaultValue: '{{done}} / {{total}}',
        })}</p>,
      }
    }))
  }

  return <details open={running} className="space-y-2 border-t border-space-border pt-2 text-sm">
    <summary id={titleId} className="w-fit cursor-pointer rounded text-gray-300 hover:text-neon-cyan focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan">
      {t('build.stageDetails')}
    </summary>
    {current && <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-xs text-gray-300">
      <span role="status" className="font-semibold text-neon-cyan">{current.step
        ? t('build.currentStep', { layer: current.layer, step: current.step }) : current.layer}</span>
      {current.total > 0 && <span className="tabular-nums">{t('build.stepCount', { done: current.done, total: current.total })}</span>}
    </div>}
    <ProgressTimeline items={items} titleId={titleId} current={current?.id} follow={running} />
  </details>
}
