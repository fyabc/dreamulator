import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import type { ClimateTrialForcing, ClimateTrialResult } from '../api/climateTrials'
import { savedClimateKey } from '../api/climateTrials'
import { ClimateModelPicker } from './ClimateModelPicker'
import { EbmTrialProgress } from './EbmTrialProgress'

const fields = [
  { key: 'axial_tilt_deg', label: 'tilt', min: 0, max: 90 },
  { key: 'rotation_period_days', label: 'rotation', min: 0 },
  { key: 'albedo', label: 'albedo', min: 0, max: 1 },
  { key: 'greenhouse_warming_k', label: 'greenhouse', min: 0 },
] as const

function errorCode(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

export default function EbmClimateLab({ search, open, onResult, onShow, onPreviewMode }: {
  search: URLSearchParams
  open: boolean
  onResult: (result: ClimateTrialResult) => void
  onShow: () => void
  onPreviewMode?: () => void
}) {
  const { t, i18n } = useTranslation('playground')
  const queryClient = useQueryClient()
  const world = search.get('world') ?? ''
  const planet = search.get('planet') ?? ''
  const branch = search.get('branch') || null
  const [overrides, setOverrides] = useState<Partial<ClimateTrialForcing>>({})
  const shownId = useRef<string | null>(null)
  const [lastResult, setLastResult] = useState<ClimateTrialForcing | null>(null)
  const [cancelled, setCancelled] = useState(false)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const browser = Boolean(onPreviewMode)
  const inputs = useQuery({
    queryKey: ['climate-trial-inputs', world, planet, branch],
    queryFn: () => api.getClimateTrialInputs(world, planet, branch), retry: false,
  })
  const start = useMutation({
    mutationFn: async ({ forcing, signal }: { forcing: ClimateTrialForcing; signal: AbortSignal }) => ({
      job: await api.startClimateTrial(world, planet, branch, forcing, signal), forcing,
    }),
  })
  const id = start.data?.job.id
  const status = useQuery({
    queryKey: ['climate-trial-job', world, planet, id],
    queryFn: ({ signal }) => api.getClimateTrial(world, planet, id!, signal), enabled: Boolean(id), retry: 1,
    refetchInterval: query => query.state.status !== 'error' && query.state.data?.state !== 'succeeded' &&
      query.state.data?.state !== 'failed' ? 650 : false,
  })
  const job = status.data ?? start.data?.job
  const products = useQuery({
    queryKey: ['climate-trial-products', world, planet, id],
    queryFn: () => api.getClimateTrialProducts(world, planet, id!), enabled: job?.state === 'succeeded',
    staleTime: Infinity, gcTime: 0, retry: false,
  })
  const submission = start.data
  useEffect(() => {
    if (!submission || !products.data || shownId.current === submission.job.id) return
    shownId.current = submission.job.id
    setLastResult(submission.forcing)
    onResult({ ...products.data, forcing: submission.forcing })
  }, [submission, products.data, onResult])

  const current = inputs.data ? { ...inputs.data, ...overrides } : null
  const valid = current && fields.every(field => {
    const value = current[field.key]
    return Number.isFinite(value) && (field.key === 'rotation_period_days' ? value > 0 : value >= field.min) &&
      (!('max' in field) || value <= field.max)
  })
  const loadingProducts = job?.state === 'succeeded' && products.isPending
  const running = job?.state === 'queued' || job?.state === 'running'
  const busy = start.isPending || running || loadingProducts
  const error = inputs.error ?? start.error ?? status.error ?? products.error ?? job?.error
  const reason = error ? errorCode(error) : null
  const errorKey = `ebm.error.${reason}`
  const buildPath = `/worlds/${encodeURIComponent(world)}${branch ? `?branch=${encodeURIComponent(branch)}` : ''}`
  const retry = inputs.isError ? inputs.refetch : status.isError ? status.refetch : products.isError ? products.refetch : null
  const phase = start.isPending ? 'queued' : job?.state === 'succeeded' ? (products.data ? 'done' : 'loading') : job?.stage
  const format = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 0 })
  const save = useMutation({
    mutationFn: (jobId: string) => api.saveClimateTrial(world, planet, jobId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: savedClimateKey(world) }),
  })
  const saved = save.data?.id === id && Boolean(id)
  const saveError = save.variables === id && save.error ? errorCode(save.error) : null
  const worldData = `/worlds/${encodeURIComponent(world)}?${new URLSearchParams(branch ? { tab: 'data', branch } : { tab: 'data' })}`

  return <form className="space-y-3" onSubmit={event => {
    event.preventDefault()
    if (!current || !valid || busy || save.isPending) return
    controller.current?.abort()
    controller.current = new AbortController()
    setCancelled(false)
    start.mutate({ forcing: current, signal: controller.current.signal })
  }}>
    <ClimateModelPicker />
    <p className="text-xs leading-relaxed text-gray-300">{t(browser ? 'ebm.browser.description' : 'ebm.description')}</p>
    {inputs.isPending && <p role="status" className="text-xs text-gray-300">{t('ebm.readingInputs')}</p>}
    {current && <fieldset disabled={busy} className="space-y-2">
      <legend className="mb-2 text-xs font-semibold text-gray-200">{t('params.title')}</legend>
      {fields.map(field => <label key={field.key} className="flex items-center justify-between gap-2 text-xs text-gray-300">
        <span>{t(`params.${field.label}`)}</span>
        <input type="number" required step="any" min={field.min} max={'max' in field ? field.max : undefined}
          value={Number.isFinite(current[field.key]) ? current[field.key] : ''}
          onChange={event => {
            const value = event.target.valueAsNumber
            setOverrides(previous => ({ ...previous, [field.key]: value }))
          }} className="w-24 shrink-0 rounded border border-space-border bg-space-surface px-2 py-1.5 text-right text-sm tabular-nums text-gray-200 focus-visible:outline focus-visible:outline-neon-cyan disabled:opacity-70" />
      </label>)}
    </fieldset>}
    {current && !valid && <p className="text-xs text-amber-200">{t('ebm.error.params')}</p>}
    {current && <div className="flex flex-wrap items-center gap-2">
      <button type="submit" disabled={!valid || busy || save.isPending} className="atlas-tool-button min-h-9 text-xs">
        {t(lastResult ? 'action.recompute' : 'action.run')}
      </button>
      {lastResult && <button type="button" onClick={onShow} className="atlas-tool-button min-h-9 text-xs">{t('ebm.show')}</button>}
      {browser && busy && <button type="button" onClick={() => {
        controller.current?.abort()
        start.reset()
        setCancelled(true)
      }} className="atlas-tool-button min-h-9 text-xs">{t('ebm.browser.cancel')}</button>}
    </div>}
    {cancelled && <p role="status" className="text-xs text-gray-300">{t('ebm.browser.cancelled')}</p>}
    {phase && <EbmTrialProgress phase={phase} job={job} interrupted={Boolean(error)} open={open} starting={start.isPending} browser={browser} format={format} />}
    {lastResult && phase === 'done' && !error && <p className="text-xs text-gray-300">
      {t(fields.some(({ key }) => lastResult[key] !== current?.[key]) ? 'status.previousResult' : 'ebm.ready', {
        cells: format.format(job?.cells ?? 0), seconds: format.format(job?.elapsed_seconds ?? 0),
      })}
    </p>}
    {!browser && id && phase === 'done' && !error && <div className="space-y-1.5 border-t border-space-border pt-3 text-xs">
      {saved ? <>
        <p role="status" className="text-neon-cyan">{t('ebm.saved.confirmed')}</p>
        <Link to={worldData} className="inline-flex min-h-9 items-center text-neon-cyan hover:underline">{t('trial.openData')}</Link>
      </> : <>
        <button type="button" disabled={save.isPending} onClick={() => save.mutate(id)} className="atlas-tool-button min-h-9 text-xs">
          {t(save.isPending ? 'ebm.saved.saving' : 'ebm.saved.save')}
        </button>
        <p className="text-gray-400">{t('ebm.saved.help')}</p>
        {saveError && <p role="alert" className="text-red-200">
          {t(saveError === 'trial_surface_missing' ? 'ebm.saved.surfaceMissing' : 'ebm.saved.saveFailed')}
        </p>}
      </>}
    </div>}
    {reason && <div className="space-y-1 text-xs text-red-200">
      <p role="alert">{t(i18n.exists(errorKey, { ns: 'playground' }) ? errorKey : 'ebm.error.generic')}</p>
      {(reason === 'build_mesh' || reason === 'build_inputs') && <Link to={buildPath} className="inline-flex min-h-8 items-center text-neon-cyan underline">{t('ebm.openWorld')}</Link>}
      {retry && <button type="button" className="atlas-tool-button text-xs" onClick={() => void retry()}>{t('trial.retry')}</button>}
      <details className="text-gray-300"><summary className="cursor-pointer">{t('error.details')}</summary>
        <p className="max-h-40 overflow-auto whitespace-pre-wrap break-words">{job?.error_detail ?? reason}</p></details>
    </div>}
    {onPreviewMode && !busy && <div className="border-t border-space-border pt-2">
      <button type="button" onClick={onPreviewMode} className="atlas-tool-button min-h-9 text-xs">{t('ebm.browser.usePreview')}</button>
    </div>}
  </form>
}
