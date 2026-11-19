import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { RegionRefinementJob, RegionRefinementSource } from './types'

interface Props {
  source: RegionRefinementSource
  resultUrl: (pack: string) => string
  globalReturn?: string | null
}

const ongoing = (job: RegionRefinementJob | undefined) => job?.state === 'queued' || job?.state === 'running'
const formatKm = (value: number) => Number(value.toPrecision(3))
const button = 'rounded border border-space-border bg-space-surface px-2 py-1 text-neon-cyan disabled:opacity-50'

export default function RegionRefinementPanel({ source, resultUrl, globalReturn }: Props) {
  const { t } = useTranslation('map')
  const queryClient = useQueryClient()
  const key = `dreamulator-refinement:${JSON.stringify(source)}`
  const [jobId, setJobId] = useState(() => sessionStorage.getItem(key))
  const [open, setOpen] = useState(jobId !== null)
  const [selection, setInputPx] = useState<number | null>(null)
  const query = useQuery({ queryKey: ['region-refinement-job', jobId], queryFn: () => api.getRegionRefinement(jobId!),
    enabled: jobId !== null, retry: false, refetchInterval: (current) => ongoing(current.state.data) ? 1000 : false })
  const inputPx = selection ?? query.data?.plan.input_px ?? 512
  const request = source.kind === 'world' ? { ...source, input_px: inputPx } : source
  const plan = useQuery({ queryKey: ['region-refinement-plan', request], queryFn: () => api.planRegionRefinement(request),
    enabled: open && !ongoing(query.data) && (jobId === null || !query.isPending), retry: false })
  const start = useMutation({ mutationFn: api.startRegionRefinement, onSuccess: (job) => {
    queryClient.setQueryData(['region-refinement-job', job.id], job)
    sessionStorage.setItem(key, job.id)
    setJobId(job.id)
  } })
  const cancel = useMutation({ mutationFn: api.cancelRegionRefinement, onSuccess: () => void query.refetch() })
  const active = ongoing(query.data)
  const missing = query.error instanceof ApiError && query.error.status === 404
  const display = active ? query.data?.plan : plan.data
  const detail = cancel.error ?? start.error ?? plan.error
  const job = query.data

  return <details open={open} className="rounded border border-space-border p-2 text-xs text-gray-400"
    onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer font-medium text-neon-cyan">{t('packs.refinement.title')}</summary>
    <div className="mt-2 space-y-2">
      <p>{t('packs.refinement.redraw')}</p>
      {source.kind === 'world' && !active && <label className="block">
        <span className="mr-2">{t('packs.refinement.grid')}</span>
        <select className={button} value={inputPx} onChange={(event) => setInputPx(Number(event.target.value))}>
          {[256, 512, 1024].map((pixels) => <option key={pixels} value={pixels}>{pixels * 2} × {pixels * 2}</option>)}
        </select>
      </label>}
      {display && <>
        <p>{t('packs.refinement.plan', { span: display.span_km, input: display.input_px, output: display.output_px,
          step: formatKm(display.span_km / display.output_px) })}</p>
        {display.native_scale_km !== null && <p>{t('packs.refinement.nativeScale', { scale: formatKm(display.native_scale_km) })}</p>}
      </>}
      {active && job && <div className="space-y-2">
        <p role="status">{t(`packs.refinement.stage.${job.stage}`)} · {t('packs.refinement.seconds', { count: job.elapsed_seconds })}</p>
        {job.stage !== 'publishing' && <button type="button" className={button} disabled={cancel.isPending || cancel.isSuccess}
          onClick={() => cancel.mutate(job.id)}>{t(cancel.isSuccess ? 'packs.refinement.cancelling' : 'packs.refinement.cancel')}</button>}
      </div>}
      {job?.state === 'failed' && <p role="alert" className="break-words text-red-300">{t('packs.refinement.failed')} {job.error}</p>}
      {job?.state === 'cancelled' && <p role="status">{t('packs.refinement.cancelled')}</p>}
      {job?.result_pack && <Link className="block text-neon-cyan hover:underline" to={resultUrl(job.result_pack)}
        state={{ regionReturn: globalReturn }}>{t('packs.refinement.result')}</Link>}
      {query.error && !missing && <button type="button" className={button} onClick={() => void query.refetch()}>
        {t('packs.refinement.reconnect')}</button>}
      {missing && <p role="status">{t('packs.refinement.missing')}</p>}
      {detail && <p role="alert" className="break-words text-red-300">{detail.message}</p>}
      {plan.isError && <button type="button" className={button} onClick={() => void plan.refetch()}>{t('packs.export.retry')}</button>}
      {!active && <button type="button" className={button} disabled={!plan.data || plan.isFetching || plan.isError || start.isPending ||
        (jobId !== null && !job && !missing)} onClick={() => { cancel.reset(); start.mutate(request) }}>
        {t('packs.refinement.start')}</button>}
    </div>
  </details>
}
