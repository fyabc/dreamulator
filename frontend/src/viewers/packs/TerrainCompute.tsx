import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import type { ElevationRaster } from './elevationRaster'
import { getWebGpuDevice, type WebGpuDevice } from './webGpuDevice'
import type { TerrainProgress, TerrainStage } from './terrainRefinement'
import { maxTerrainSpanKm, minTerrainSpanKm } from './terrainTiles'

const modelUrl = import.meta.env.VITE_TD_MODEL_URL?.trim()
const modelHash = import.meta.env.VITE_TD_MODEL_SHA256?.trim().toLowerCase()
const loadRefinement = import.meta.env.VITE_STATIC_MODE === 'true' && import.meta.env.VITE_TD_MODEL_URL
  ? () => import('./runTerrainRefinement') : null
const button = 'rounded border border-space-border bg-space-surface px-2 py-1 text-neon-cyan disabled:opacity-50'

interface BrowserInput {
  raster: ElevationRaster | null
  spanKm: number
  seaLevel: number
  onResult: (result: { raster: ElevationRaster; manifestSha256: string }) => void
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

type ProgressState = {
  kind: 'running' | 'cancelling'
  progress: TerrainProgress
  startedAt: number
  phaseStartedAt: number
  cacheUnavailable: boolean
}
type RunState = ProgressState | { kind: 'idle' | 'cancelled' } |
  { kind: 'error'; progress: TerrainProgress } | { kind: 'completed'; elapsed: number; cacheUnavailable: boolean }

const stageNumber: Record<TerrainStage, number> = { coarse: 1, base: 2, decoder: 3 }

function elapsedTime(milliseconds: number) {
  const seconds = Math.floor(Math.max(0, milliseconds) / 1000)
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
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
    return <p role="alert" className="text-red-300">{t('failedAt', { heading })} {t('error')}</p>
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
      <progress className="w-full accent-neon-cyan" aria-label={phase} value={progress.done} max={progress.total} />
    </>}
    <p>{t('elapsed', { run: elapsedTime(now - state.startedAt), phase: elapsedTime(now - state.phaseStartedAt) })}</p>
    {state.cacheUnavailable && <p className="text-amber-200">{t('cacheUnavailable')}</p>}
  </div>
}

function BrowserRefinement({ gpu, input }: { gpu: WebGpuDevice | null | undefined; input: BrowserInput }) {
  const { t } = useTranslation('map', { keyPrefix: 'packs.compute' })
  const controller = useRef<AbortController | null>(null)
  const [state, setState] = useState<RunState>({ kind: 'idle' })
  const busy = state.kind === 'running' || state.kind === 'cancelling'
  const supportedSpan = input.spanKm >= minTerrainSpanKm && input.spanKm <= maxTerrainSpanKm
  const configured = modelUrl && modelHash && /^[a-f0-9]{64}$/.test(modelHash) && loadRefinement
  useEffect(() => () => {
    controller.current?.abort()
    controller.current = null
  }, [])

  const run = async () => {
    if (gpu?.kind !== 'hardware' || !configured || !modelUrl || !modelHash || !loadRefinement || !input.raster ||
      !supportedSpan || controller.current) return
    const task = new AbortController()
    controller.current = task
    const startedAt = performance.now()
    let phaseStartedAt = startedAt
    let cacheUnavailable = false
    let latest: TerrainProgress = { phase: 'prepare' }
    setState({ kind: 'running', progress: latest, startedAt, phaseStartedAt, cacheUnavailable })
    try {
      const base = new URL(`${modelUrl.replace(/\/$/, '')}/`, new URL(import.meta.env.BASE_URL, window.location.href))
      if (base.protocol !== 'https:' && !(base.protocol === 'http:' && base.origin === window.location.origin)) {
        throw new Error('Invalid TD asset origin')
      }
      const { runTerrainRefinement } = await loadRefinement()
      task.signal.throwIfAborted()
      const job = { base: base.href, hash: modelHash, raster: input.raster, spanKm: input.spanKm, sea: input.seaLevel }
      const result = await runTerrainRefinement(job, gpu, task.signal, (progress) => {
        if (controller.current !== task || task.signal.aborted) return
        if (progress.phase !== latest.phase || progress.stage !== latest.stage) phaseStartedAt = performance.now()
        if (progress.phase === 'initialize' && !progress.reusable) cacheUnavailable = true
        latest = progress
        setState({ kind: 'running', progress, startedAt, phaseStartedAt, cacheUnavailable })
      })
      if (controller.current === task && !task.signal.aborted) {
        input.onResult({ raster: result, manifestSha256: modelHash })
        setState({ kind: 'completed', elapsed: performance.now() - startedAt, cacheUnavailable })
      }
    } catch (error) {
      if (controller.current === task) {
        if (!task.signal.aborted) console.error('Browser terrain refinement failed', error)
        setState(task.signal.aborted ? { kind: 'cancelled' } : { kind: 'error', progress: latest })
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

  return <details className="rounded border border-space-border p-2">
    <summary className="cursor-pointer font-medium text-neon-cyan">{t('browserTitle')}</summary>
    <div className="mt-2 space-y-2">
      {!configured ? <p>{t('notPublished')}</p> : <>
        <p>{t('browserHint')}</p>
        {!supportedSpan && <p>{t('windowLimit', { min: minTerrainSpanKm, max: maxTerrainSpanKm })}</p>}
        {gpu !== undefined && gpu?.kind !== 'hardware' && <p>{t('requiresHardware')}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="button" className={button} disabled={busy || !supportedSpan || !input.raster || gpu?.kind !== 'hardware'} onClick={() => void run()}>{t('run')}</button>
          {busy && <button type="button" className={button} disabled={state.kind === 'cancelling'} onClick={cancel}>{t('cancel')}</button>}
        </div>
        {(busy || state.kind === 'error') && <BrowserProgress state={state} />}
        {state.kind === 'completed' && <>
          <p role="status">{t('completed', { run: elapsedTime(state.elapsed) })}</p>
          {state.cacheUnavailable && <p className="text-amber-200">{t('cacheUnavailable')}</p>}
        </>}
        {state.kind === 'cancelled' && <p role="status">{t('cancelled')}</p>}
      </>}
    </div>
  </details>
}
