import { useEffect, useId, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { ClimateTrialJob } from '../api/climateTrials'
import ProgressTimeline, { type TimelineItem } from '../components/ProgressTimeline'

const localStages = [
  'queued', 'reading', 'temperature', 'wind', 'ocean', 'precipitation',
  'koppen', 'writeback', 'export', 'loading',
]
const browserStages = ['queued', 'browserRuntime', ...localStages.slice(1)]

export function EbmTrialProgress({ phase, job, interrupted, open, starting, browser, format }: {
  phase: string
  job: ClimateTrialJob | undefined
  interrupted: boolean
  open: boolean
  starting: boolean
  browser: boolean
  format: Intl.NumberFormat
}) {
  const { t } = useTranslation('playground')
  const stages = browser ? browserStages : localStages
  const stageLabel = (stage: string) => t(`ebm.stage.${browser && stage === 'queued' ? 'browserQueued' : stage}`, { defaultValue: stage })
  const title = useId()
  const section = useRef<HTMLElement>(null)
  const complete = phase === 'done'
  const activeIndex = complete ? stages.length - 1 : stages.indexOf(phase)

  useEffect(() => {
    if (starting && open) section.current?.scrollIntoView({ block: 'nearest' })
  }, [starting, open])

  const items = stages.map((stage, index): TimelineItem => {
    const done = complete || index < activeIndex
    const active = !complete && index === activeIndex
    return {
      id: stage,
      state: done ? 'done' : active ? interrupted ? 'failed' : 'active' : 'pending',
      label: <>{stageLabel(stage)}{done && <span className="sr-only"> · {t('ebm.progress.done')}</span>}</>,
      detail: job && active && phase === job.stage && <>
        {job.months_done != null && <p>{t('ebm.months', { pass: job.moisture_pass, done: job.months_done, total: job.months_total })}</p>}
        <p>{t('ebm.progress.stageElapsed', { seconds: format.format(job.stage_seconds) })}</p>
      </>,
    }
  })

  return <section ref={section} aria-labelledby={title} className="space-y-2 border-t border-space-border pt-3 text-xs">
    <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
      <h3 id={title} className="font-semibold text-gray-100">{t('ebm.progress.title')}</h3>
      <span className="tabular-nums text-gray-300">{t('ebm.progress.steps', { done: complete ? stages.length : Math.max(0, activeIndex), total: stages.length })}</span>
    </div>
    <div role="status" className="sr-only">
      {complete ? t('ebm.progress.ready') : t('ebm.progress.active', { stage: stageLabel(phase) })}
    </div>
    <ProgressTimeline items={items} titleId={title} current={stages[activeIndex]} follow={open} />
    {job && !complete && <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1 tabular-nums text-gray-300">
      <span>{t('ebm.progress.totalElapsed', { seconds: format.format(job.elapsed_seconds) })}</span>
      {job.cells != null && <span>{t('ebm.grid', { cells: format.format(job.cells) })}</span>}
    </div>}
  </section>
}
