import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import type { ElevationRaster } from './elevationRaster'
import { getWebGpuDevice, type WebGpuDevice } from './webGpuDevice'
import type { TerrainProgress, TerrainStage } from './terrainRefinement'
import { defaultEnhancedGain, defaultTerrainSeed, enhancedTerrainGain, maxEnhancedGain, maxTerrainSeed, minEnhancedGain,
  nativeTerrainSpacing, recommendTerrain, terrainRecipe, terrainSeed, type TerrainMethod, type TerrainRecipe } from './terrainRecommendation'
import { TerrainParameter } from './TerrainParameter'
import { clearTerrainModelCache, readTerrainModelCacheBytes } from './terrainModelCache'
import { makeTerrainPlan, maxTerrainSpanKm, minTerrainSpanKm, supportsTerrainSpan } from './terrainTiles'

const modelUrl = import.meta.env.VITE_TD_MODEL_URL?.trim()
const modelHash = import.meta.env.VITE_TD_MODEL_SHA256?.trim().toLowerCase()
const loadRefinement = import.meta.env.VITE_STATIC_MODE === 'true' && import.meta.env.VITE_TD_MODEL_URL
  ? () => import('./runTerrainRefinement') : null
const button = 'rounded border border-space-border bg-space-surface px-2 py-1 text-neon-cyan disabled:opacity-50'
const modelCacheKey = ['terrain-model-cache'] as const

function formatCacheSize(bytes: number, language: string) {
  const [unit, divisor] = bytes >= 1e9 ? ['gigabyte', 1e9] as const : bytes >= 1e6 ? ['megabyte', 1e6] as const
    : bytes >= 1e3 ? ['kilobyte', 1e3] as const : ['byte', 1] as const
  return new Intl.NumberFormat(language, { style: 'unit', unit, unitDisplay: 'short', maximumFractionDigits: 2 }).format(bytes / divisor)
}

export interface BrowserTerrainResult {
  raster: ElevationRaster
  manifestSha256: string
  nativeSpacingKm: number | null
  recommendation: TerrainMethod | null
  recipe: TerrainRecipe
}

interface BrowserInput {
  raster: ElevationRaster | null
  spanKm: number
  sourceRowSpacingKm: number | null
  nativeEstimateKm?: number | null
  seaLevel: number
  onResult: (result: BrowserTerrainResult) => void
}

export default function TerrainCompute({ browser, children }: { browser?: BrowserInput; children?: ReactNode }) {
  const { t } = useTranslation('map', { keyPrefix: 'packs.compute' })
  const staticMode = isStaticMode()
  const local = useQuery({ queryKey: ['region-compute-device'], queryFn: api.getRegionDevice,
    enabled: !staticMode, retry: false, staleTime: 5 * 60 * 1000 })
  const [gpu, setGpu] = useState<WebGpuDevice | null>()
  useEffect(() => {
    if (!staticMode) return
    let mounted = true
    void getWebGpuDevice().then((device) => { if (mounted) setGpu(device) })
    return () => { mounted = false }
  }, [staticMode])

  const label = t(staticMode ? 'browserConnection' : 'localConnection')
  const name = staticMode
    ? gpu === undefined ? t('checking') : gpu === null ? t('unavailable') : gpu.name ?? t('unknownDevice')
    : local.isPending ? t('checking') : local.data?.kind === 'cpu' ? t('cpu') : local.data?.name ?? t('unavailable')
  const kind = staticMode && gpu && gpu.kind !== 'hardware' ? t(kinds[gpu.kind]) : null
  return <section aria-label={t('title')} className="space-y-2 text-xs text-gray-400">
    <div className="rounded border border-space-border bg-space-surface p-2">
      <p className="font-medium text-gray-200">{t('title')}</p>
      <p role="status" className="mt-1 break-words">{label} · {name}{kind && ` (${kind})`}</p>
    </div>
    {staticMode ? browser && <BrowserRefinement gpu={gpu} input={browser} /> : children}
  </section>
}

const kinds = { software: 'software', unknown: 'unknownKind' } as const

type CoarseTiming = readonly [firstMs: number, secondMs?: number]

type ProgressState = {
  kind: 'running' | 'cancelling'
  progress: TerrainProgress
  startedAt: number
  phaseStartedAt: number
  cacheUnavailable: boolean
  coarseTiming?: CoarseTiming
}
type RunState = ProgressState | { kind: 'idle' | 'cancelled' } |
  { kind: 'error'; progress: TerrainProgress; deviceLost: boolean; coarseTiming?: CoarseTiming } |
  { kind: 'completed'; elapsed: number; cacheUnavailable: boolean; coarseTiming?: CoarseTiming }

const stageNumber: Record<TerrainStage, number> = { coarse: 1, base: 2, decoder: 3 }

function elapsedTime(milliseconds: number) {
  const seconds = Math.floor(Math.max(0, milliseconds) / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

function InferenceTimings({ timing }: { timing: CoarseTiming }) {
  const { t, i18n } = useTranslation('map', { keyPrefix: 'packs.compute' })
  const format = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 })
  const [firstMs, secondMs] = timing
  const first = format.format(firstMs / 1000)
  return <p className="tabular-nums">{secondMs === undefined ? t('firstRunTime', { first })
    : t('firstTwoRunTimes', { first, second: format.format(secondMs / 1000) })}</p>
}

function BrowserProgress({ state }: { state: ProgressState | Extract<RunState, { kind: 'error' }> }) {
  const { t, i18n } = useTranslation('map', { keyPrefix: 'packs.compute' })
  const [now, setNow] = useState(() => performance.now())
  useEffect(() => {
    if (state.kind === 'error') return
    const timer = window.setInterval(() => setNow(performance.now()), 1000)
    return () => window.clearInterval(timer)
  }, [state.kind])

  const { progress } = state
  const phase = t(`phase.${progress.phase}`)
  const heading = progress.stage ? t('stageProgress', { stage: t(`stage.${progress.stage}`), phase, step: stageNumber[progress.stage] }) : phase
  if (state.kind === 'error') {
    return <>
      <p role="alert" className="text-red-300">{t('failedAt', { heading })} {t(state.deviceLost ? 'deviceLost' : 'error')}</p>
      {state.coarseTiming && <InferenceTimings timing={state.coarseTiming} />}
    </>
  }

  const number = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 1 })
  return <div className="space-y-1 border-t border-space-border pt-2">
    <p role="status" className="text-gray-200">{state.kind === 'cancelling' ? t('cancelling') : heading}</p>
    {state.kind === 'running' && (progress.phase === 'download' || progress.phase === 'cacheRead') && <>
      <p>{t('received', { received: number.format(progress.received / 1e6), total: number.format(progress.total / 1e6),
        percent: Math.floor(progress.received / progress.total * 100) })}</p>
      <progress className="w-full accent-neon-cyan" aria-label={phase} value={progress.received} max={progress.total} />
    </>}
    {state.kind === 'running' && progress.phase === 'initialize' && <p>{t('initializeHint')}</p>}
    {state.kind === 'running' && progress.phase === 'tiles' && <>
      <p>{progress.done === progress.total ? t('tilesComplete', progress) : t('tilesActive', { ...progress, next: progress.done + 1 })}</p>
      {progress.inference && <>
        <p>{t('inferenceProgress', progress.inference)}</p>
        {progress.inference.status === 'preparing' && <p>{t('inferencePreparing')}</p>}
        {progress.inference.status === 'waiting' && <>
          <p>{t('inferenceWaiting', { step: progress.inference.done + 1,
            elapsed: elapsedTime(performance.timeOrigin + now - progress.inference.startedAt) })}</p>
          {progress.done === 0 && progress.inference.done === 0 && <p>{t('firstInferenceHint')}</p>}
        </>}
        {progress.inference.status === 'applying' && <p>{t('inferenceApplying', { step: progress.inference.done + 1 })}</p>}
      </>}
      <progress className="w-full accent-neon-cyan" aria-label={phase} value={progress.done} max={progress.total} />
    </>}
    {state.coarseTiming && <InferenceTimings timing={state.coarseTiming} />}
    <p>{t('elapsed', { run: elapsedTime(now - state.startedAt), phase: elapsedTime(now - state.phaseStartedAt) })}</p>
    {state.kind === 'running' && <p>{t('foregroundHint')}</p>}
    {state.cacheUnavailable && <p className="text-amber-200">{t('cacheUnavailable')}</p>}
  </div>
}

function BrowserBudget({ plan, spanKm, sourceRowSpacingKm }: {
  plan: ReturnType<typeof makeTerrainPlan>; spanKm: number; sourceRowSpacingKm: number | null
}) {
  const { t, i18n } = useTranslation('map', { keyPrefix: 'packs.compute.budget' })
  const number = new Intl.NumberFormat(i18n.resolvedLanguage, { maximumSignificantDigits: 3 })
  const rows = [
    { key: 'window', value: t('kilometres', { km: number.format(spanKm) }) },
    { key: 'sourceGrid', value: sourceRowSpacingKm === null ? null : t('kilometres', { km: number.format(sourceRowSpacingKm) }) },
    { key: 'inputGrid', value: t('inputValue', { size: plan.inputSize, km: number.format(spanKm / plan.inputSize) }) },
    { key: 'outputGrid', value: t('outputValue', { size: plan.size }) },
    { key: 'outputSpacing', value: t('metres', { metres: number.format(spanKm * 1000 / plan.size) }) },
    { key: 'coarseTiles', value: t('tileCount', { count: plan.totals.coarse }) },
    { key: 'baseTiles', value: t('tileCount', { count: plan.totals.base }) },
    { key: 'decoderTiles', value: t('tileCount', { count: plan.totals.decoder }) },
  ]
  return <div className="rounded border border-space-border bg-space-surface p-2">
    <p className="font-medium text-gray-200">{t('title')}</p>
    <dl className="mt-1 space-y-0.5">
      {rows.map(({ key, value }) => value !== null && <div key={key} className="flex items-baseline justify-between gap-2">
        <dt title={t(`hint.${key}`)}>{t(key)}</dt>
        <dd className="whitespace-nowrap text-right tabular-nums text-gray-200">{value}</dd>
      </div>)}
    </dl>
  </div>
}

function BrowserRefinement({ gpu, input }: { gpu: WebGpuDevice | null | undefined; input: BrowserInput }) {
  const { t, i18n } = useTranslation('map', { keyPrefix: 'packs.compute' })
  const helpId = useId()
  const controller = useRef<AbortController | null>(null)
  const queryClient = useQueryClient()
  const [state, setState] = useState<RunState>({ kind: 'idle' })
  const [modelManagerOpen, setModelManagerOpen] = useState(false)
  const [nativeOverride, setNativeOverride] = useState<string | null>(null)
  const nativeInput = nativeOverride ?? (input.nativeEstimateKm == null ? '' : String(Number(input.nativeEstimateKm.toPrecision(6))))
  const [choice, setChoice] = useState<TerrainMethod | null>(null)
  const [seed, setSeed] = useState('')
  const [gain, setGain] = useState('')
  const [wavelength, setWavelength] = useState('')
  const busy = state.kind === 'running' || state.kind === 'cancelling'
  const plan = useMemo(() => supportsTerrainSpan(input.spanKm) ? makeTerrainPlan(input.spanKm) : null, [input.spanKm])
  const configured = modelUrl && modelHash && /^[a-f0-9]{64}$/.test(modelHash) && loadRefinement
  const cache = useQuery({ queryKey: modelCacheKey, queryFn: readTerrainModelCacheBytes,
    enabled: modelManagerOpen && !busy, staleTime: 0, retry: false })
  const clearCache = useMutation({ mutationFn: clearTerrainModelCache,
    onSettled: () => queryClient.invalidateQueries({ queryKey: modelCacheKey }) })
  const canClearCache = !busy && !clearCache.isPending && !cache.isFetching && !cache.isError && !!cache.data
  const nativeSpacingKm = nativeTerrainSpacing(nativeInput)
  const invalidSpacing = nativeInput !== '' && nativeSpacingKm === null
  const recommendation = plan ? recommendTerrain(nativeSpacingKm, input.spanKm / plan.inputSize, input.spanKm / plan.size) : null
  const method = choice ?? recommendation?.method
  const outputKm = plan ? input.spanKm / plan.size : 0
  const minimumWavelength = outputKm * 4
  const defaultWavelength = nativeSpacingKm === null ? null : nativeSpacingKm * 4
  const invalidWavelength = wavelength !== '' && (nativeTerrainSpacing(wavelength) ?? 0) < minimumWavelength
  const recipe = plan ? terrainRecipe(method, nativeSpacingKm, outputKm, { seed, gain, wavelength }) : null
  const canRun = !invalidSpacing && !!recipe && !!input.raster && gpu?.kind === 'hardware'
  useEffect(() => () => {
    controller.current?.abort()
    controller.current = null
  }, [])

  const run = async () => {
    if (!canRun || !recipe || gpu?.kind !== 'hardware' || !configured || !modelUrl || !modelHash || !loadRefinement || !input.raster ||
      controller.current || clearCache.isPending) return
    clearCache.reset()
    const task = new AbortController()
    controller.current = task
    const startedAt = performance.now()
    let phaseStartedAt = startedAt
    let cacheUnavailable = false
    let coarseTiming: CoarseTiming | undefined
    let latest: TerrainProgress = { phase: 'prepare' }
    setState({ kind: 'running', progress: latest, startedAt, phaseStartedAt, cacheUnavailable })
    try {
      const base = new URL(`${modelUrl.replace(/\/$/, '')}/`, new URL(import.meta.env.BASE_URL, window.location.href))
      if (base.protocol !== 'https:' && !(base.protocol === 'http:' && base.origin === window.location.origin)) {
        throw new Error('Invalid TD asset origin')
      }
      const { runTerrainRefinement } = await loadRefinement()
      task.signal.throwIfAborted()
      const job = { base: base.href, hash: modelHash, raster: input.raster, spanKm: input.spanKm, sea: input.seaLevel, recipe }
      const result = await runTerrainRefinement(job, gpu, task.signal, (progress) => {
        if (controller.current !== task || task.signal.aborted) return
        if (progress.phase !== latest.phase || progress.stage !== latest.stage) phaseStartedAt = performance.now()
        if (progress.phase === 'initialize' && !progress.reusable) cacheUnavailable = true
        if (progress.phase === 'tiles' && progress.stage === 'coarse' && progress.done === 0 && progress.inference?.status === 'completed') {
          const { done, runMs } = progress.inference
          if (done === 1) coarseTiming = [runMs]
          else if (done === 2 && coarseTiming) coarseTiming = [coarseTiming[0], runMs]
        }
        latest = progress
        setState({ kind: 'running', progress, startedAt, phaseStartedAt, cacheUnavailable, coarseTiming })
      })
      if (controller.current === task && !task.signal.aborted) {
        input.onResult({ raster: result, manifestSha256: modelHash, nativeSpacingKm, recommendation: recommendation?.method ?? null, recipe })
        setState({ kind: 'completed', elapsed: performance.now() - startedAt, cacheUnavailable, coarseTiming })
      }
    } catch (error) {
      if (controller.current === task) {
        if (!task.signal.aborted) console.error('Browser terrain refinement failed', error)
        setState(task.signal.aborted ? { kind: 'cancelled' } : { kind: 'error', progress: latest, coarseTiming,
          deviceLost: error instanceof DOMException && error.name === 'WebGpuDeviceLostError' })
      }
    } finally {
      if (controller.current === task) {
        if (task.signal.aborted) setState({ kind: 'cancelled' })
        task.abort()
        controller.current = null
      }
    }
  }

  const cancel = () => {
    controller.current?.abort()
    setState((current) => current.kind === 'running' ? { ...current, kind: 'cancelling' } : current)
  }

  const clearModels = () => {
    if (!canClearCache || controller.current) return
    if (window.confirm(t('modelCache.confirm'))) clearCache.mutate()
  }

  return <details className="rounded border border-space-border p-2">
    <summary className="cursor-pointer font-medium text-neon-cyan">{t('browserTitle')}</summary>
    <div className="mt-2 space-y-2">
      {!configured ? <p>{t('notPublished')}</p> : <>
        {!plan && <p>{t('windowLimit', { min: minTerrainSpanKm, max: maxTerrainSpanKm })}</p>}
        {plan && !busy && <>
          <BrowserBudget plan={plan} spanKm={input.spanKm} sourceRowSpacingKm={input.sourceRowSpacingKm} />
          <div className="space-y-1">
            <label className="flex items-center justify-between gap-1" title={t('method.nativeSpacingHint')}>
              <span>{t('method.nativeSpacing')}</span>
              <input type="number" step="any" min="0" inputMode="decimal" value={nativeInput}
                onChange={(event) => setNativeOverride(event.currentTarget.value)} placeholder={t('method.unknown')}
                aria-describedby={`${helpId}-native`}
                aria-invalid={invalidSpacing} className="w-20 rounded border border-space-border bg-space-surface p-1 text-right text-gray-200" />
            </label>
            <p id={`${helpId}-native`}>{t(input.nativeEstimateKm == null ? 'method.nativeSpacingHelp' : 'method.nativeSpacingEstimate')}</p>
            <p id={`${helpId}-reason`} aria-live="polite">{t(invalidSpacing ? 'method.invalidSpacing' : `method.reason.${recommendation?.reason ?? 'unknown'}`)}</p>
            <label className="flex items-center justify-between gap-1" title={t('method.methodHint')}>
              <span>{t('method.label')}</span>
              <select className={`${button} min-w-0`} aria-describedby={`${helpId}-method ${helpId}-reason`}
                value={choice ?? ''} onChange={(event) => {
                const value = event.currentTarget.value
                setChoice(value === 'redraw' || value === 'enhanced' || value === 'blend' ? value : null)
              }}>
                <option value="">{recommendation?.method
                  ? t('method.follow', { method: t(`method.${recommendation.method}`) }) : t('method.choose')}</option>
                <option value="redraw">{t('method.redraw')}</option>
                <option value="enhanced">{t('method.enhanced')}</option>
                <option value="blend">{t('method.blend')}</option>
              </select>
            </label>
            <p id={`${helpId}-method`}>{t(`method.help.${method ?? 'choose'}`)}</p>
            {method === 'enhanced' && <TerrainParameter label={t('parameters.gain')} value={gain} onChange={setGain}
              min={minEnhancedGain} max={maxEnhancedGain} placeholder={String(defaultEnhancedGain)}
              invalid={enhancedTerrainGain(gain) === null} help={t('parameters.gainHelp', { min: minEnhancedGain, max: maxEnhancedGain })} />}
            {method === 'blend' && <>
              <TerrainParameter label={t('parameters.wavelength')} value={wavelength} onChange={setWavelength} min={minimumWavelength}
                placeholder={defaultWavelength === null || !Number.isFinite(defaultWavelength) ? t('parameters.auto') : String(+defaultWavelength.toPrecision(5))}
                invalid={invalidWavelength} help={t(invalidWavelength ? 'parameters.wavelengthMin' : 'parameters.wavelengthHelp')} />
              {!(nativeSpacingKm !== null && nativeSpacingKm > outputKm) && <p>{t('method.blendNeedsSpacing')}</p>}
            </>}
            {method && <details className="rounded border border-space-border p-2" open={terrainSeed(seed) === null || undefined}>
              <summary className="cursor-pointer">{t('parameters.advanced')}</summary>
              <div className="mt-1">
                <TerrainParameter label={t('parameters.seed')} value={seed} onChange={setSeed} min={0} max={maxTerrainSeed} step={1}
                  placeholder={String(defaultTerrainSeed)} invalid={terrainSeed(seed) === null}
                  help={t(terrainSeed(seed) === null ? 'parameters.seedInvalid' : 'parameters.seedHelp', { max: maxTerrainSeed })} />
              </div>
            </details>}
          </div>
        </>}
        {!busy && recipe && <p>{t('browserHint')}</p>}
        {!busy && recipe && gpu !== undefined && gpu?.kind !== 'hardware' && <p>{t('requiresHardware')}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="button" className={button} disabled={busy || clearCache.isPending || !canRun} onClick={() => void run()}>{t('run')}</button>
          {busy && <button type="button" className={button} disabled={state.kind === 'cancelling'} onClick={cancel}>{t('cancel')}</button>}
        </div>
        {(busy || state.kind === 'error') && <BrowserProgress state={state} />}
        {state.kind === 'completed' && <>
          <p role="status">{t('completed', { run: elapsedTime(state.elapsed) })}</p>
          {state.coarseTiming && <InferenceTimings timing={state.coarseTiming} />}
          {state.cacheUnavailable && <p className="text-amber-200">{t('cacheUnavailable')}</p>}
        </>}
        {state.kind === 'cancelled' && <p role="status">{t('cancelled')}</p>}
      </>}
      <details className="rounded border border-space-border p-2" onToggle={(event) => setModelManagerOpen(event.currentTarget.open)}>
        <summary className="cursor-pointer">{t('modelCache.title')}</summary>
        <div className="mt-1 space-y-1">
          {(cache.isError || cache.data !== undefined || !busy) && <p role="status" className="tabular-nums">
            {cache.isError ? t('modelCache.readFailed') : cache.data !== undefined
              ? t('modelCache.size', { size: formatCacheSize(cache.data, i18n.language) })
              : t('modelCache.checking')}
          </p>}
          <p id={`${helpId}-model-cache`}>{t(busy ? 'modelCache.busy' : 'modelCache.help')}</p>
          <button type="button" className={button} disabled={!canClearCache} aria-describedby={`${helpId}-model-cache`} onClick={clearModels}>
            {t(clearCache.isPending ? 'modelCache.clearing' : 'modelCache.clear')}
          </button>
          {clearCache.isSuccess && <p role="status">{t('modelCache.cleared')}</p>}
          {clearCache.isError && <p role="alert" className="text-red-300">{t('modelCache.clearFailed')}</p>}
        </div>
      </details>
    </div>
  </details>
}
