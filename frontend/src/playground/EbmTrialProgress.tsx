import { useEffect, useId, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { ClimateTrialJob } from '../api/climateTrials'

const stages = [
  'queued', 'reading', 'temperature', 'wind', 'ocean', 'precipitation',
  'koppen', 'writeback', 'export', 'loading',
]

export function EbmTrialProgress({ phase, job, interrupted, open, starting, format }: {
  phase: string
  job: ClimateTrialJob | undefined
  interrupted: boolean
  open: boolean
  starting: boolean
  format: Intl.NumberFormat
}) {
  const { t } = useTranslation('playground')
  const title = useId()
  const section = useRef<HTMLElement>(null)
  const viewport = useRef<HTMLOListElement>(null)
  const target = useRef<HTMLLIElement>(null)
  const complete = phase === 'done'
  const activeIndex = complete ? stages.length - 1 : stages.indexOf(phase)

  useEffect(() => {
    if (starting && open) section.current?.scrollIntoView({ block: 'nearest' })
  }, [starting, open])

  useEffect(() => {
    if (!open || !target.current || !viewport.current) return
    const top = Math.max(0, target.current.offsetTop - viewport.current.clientHeight / 4)
    viewport.current.scrollTo({ top })
  }, [phase, open])

  return <section ref={section} aria-labelledby={title} className="space-y-2 border-t border-space-border pt-3 text-xs">
    <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1">
      <h3 id={title} className="font-semibold text-gray-100">{t('ebm.progress.title')}</h3>
      <span className="tabular-nums text-gray-300">{t('ebm.progress.steps', { done: complete ? stages.length : Math.max(0, activeIndex), total: stages.length })}</span>
    </div>
    <div role="status" className="sr-only">
      {complete ? t('ebm.progress.ready') : t('ebm.progress.active', { stage: t(`ebm.stage.${phase}`, { defaultValue: phase }) })}
    </div>
    <ol ref={viewport} role="list" aria-labelledby={title} tabIndex={0}
      className="relative max-h-36 overflow-y-auto rounded border border-space-border bg-space-bg py-1.5 focus-visible:outline focus-visible:outline-neon-cyan motion-safe:scroll-smooth sm:max-h-52 [scrollbar-color:#526c70_transparent]">
      {stages.map((stage, index) => {
        const done = complete || index < activeIndex
        const active = !complete && index === activeIndex
        const failed = active && interrupted
        return <li key={stage} ref={index === activeIndex ? target : undefined} aria-current={active ? 'step' : undefined}
          className="relative grid min-h-8 grid-cols-[1rem_minmax(0,1fr)] items-start gap-2 pr-2 pl-2.5">
          {index < stages.length - 1 && <span aria-hidden="true"
            className={`absolute bottom-[-.9rem] left-[1.09rem] top-3.5 w-px motion-safe:transition-colors ${done ? 'bg-neon-cyan/55' : 'bg-space-border'}`} />}
          <span aria-hidden="true" className={`relative mt-1.5 grid size-4 place-items-center rounded-full border motion-safe:transition-colors ${
            done ? 'border-neon-cyan bg-neon-cyan text-space-bg' : failed ? 'border-red-300 bg-space-bg text-red-300' : active ? 'border-neon-cyan bg-space-bg text-neon-cyan' : 'border-space-border bg-space-bg text-gray-500'
          }`}>
            {done || failed ? <svg viewBox="0 0 16 16" className="size-3" fill="none" stroke="currentColor"
              strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
              <path d={failed ? 'm5 5 6 6m0-6-6 6' : 'm3.5 8 3 3 6-6'} />
            </svg> : <span className={`${active ? 'size-1.5' : 'size-1'} rounded-full bg-current`} />}
          </span>
          <div className={`pb-1.5 pt-1.5 leading-4 ${failed ? 'text-red-200' : active ? 'font-semibold text-neon-cyan' : done ? 'text-gray-200' : 'text-gray-400'}`}>
            {t(`ebm.stage.${stage}`)}
            {done && <span className="sr-only"> · {t('ebm.progress.done')}</span>}
            {job && active && phase === job.stage && <div className="mt-1 space-y-0.5 font-normal tabular-nums text-gray-300">
              {job.months_done != null && <p>{t('ebm.months', { pass: job.moisture_pass, done: job.months_done, total: job.months_total })}</p>}
              <p>{t('ebm.progress.stageElapsed', { seconds: format.format(job.stage_seconds) })}</p>
            </div>}
          </div>
        </li>
      })}
    </ol>
    {job && !complete && <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-1 tabular-nums text-gray-300">
      <span>{t('ebm.progress.totalElapsed', { seconds: format.format(job.elapsed_seconds) })}</span>
      {job.cells != null && <span>{t('ebm.grid', { cells: format.format(job.cells) })}</span>}
    </div>}
  </section>
}
