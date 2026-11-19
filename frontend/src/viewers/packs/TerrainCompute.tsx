import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import { generateAdaptiveTerrainScale } from '../map/utils/colorScales'
import type { ElevationRaster } from './elevationRaster'
import { getWebGpuDevice, type WebGpuDevice } from './webGpuDevice'

const exampleUrl = import.meta.env.VITE_TD_EXAMPLE_URL?.trim()
const loadCoarse = import.meta.env.VITE_STATIC_MODE === 'true' && import.meta.env.VITE_TD_EXAMPLE_URL
  ? () => import('./coarseTerrain') : null
const button = 'rounded border border-space-border bg-space-surface px-2 py-1 text-neon-cyan disabled:opacity-50'

export default function TerrainCompute({ children }: { children?: ReactNode }) {
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
    {staticMode ? <CoarseExample gpu={gpu} /> : children}
  </section>
}

const kinds = { software: 'software', unknown: 'unknownKind' } as const

type RunState = { kind: 'idle' | 'loading' | 'cancelled' | 'error' } | { kind: 'running'; done: number; total: number }

function CoarseExample({ gpu }: { gpu: WebGpuDevice | null | undefined }) {
  const { t } = useTranslation('map', { keyPrefix: 'packs.compute' })
  const controller = useRef<AbortController | null>(null)
  const [state, setState] = useState<RunState>({ kind: 'idle' })
  const [output, setOutput] = useState<ElevationRaster | null>(null)
  const busy = state.kind === 'loading' || state.kind === 'running'
  useEffect(() => () => {
    controller.current?.abort()
    controller.current = null
  }, [])

  const run = async () => {
    if (gpu?.kind !== 'hardware' || !exampleUrl || !loadCoarse || controller.current) return
    const task = new AbortController()
    controller.current = task
    setState({ kind: 'loading' })
    try {
      const base = new URL(`${exampleUrl.replace(/\/$/, '')}/`, new URL(import.meta.env.BASE_URL, window.location.href))
      if (base.protocol !== 'https:' && !(base.protocol === 'http:' && base.origin === window.location.origin)) {
        throw new Error('Invalid TD asset origin')
      }
      const { runCoarseTerrain } = await loadCoarse()
      task.signal.throwIfAborted()
      const result = await runCoarseTerrain(base, gpu, task.signal, (done, total) => setState({ kind: 'running', done, total }))
      if (controller.current === task && !task.signal.aborted) {
        setOutput(result)
        setState({ kind: 'idle' })
      }
    } catch {
      if (controller.current === task) {
        setState({ kind: task.signal.aborted ? 'cancelled' : 'error' })
      }
    } finally {
      if (controller.current === task) {
        if (task.signal.aborted) setState({ kind: 'cancelled' })
        task.abort()
        controller.current = null
      }
    }
  }

  return <details className="rounded border border-space-border p-2">
    <summary className="cursor-pointer font-medium text-neon-cyan">{t('exampleTitle')}</summary>
    <div className="mt-2 space-y-2">
      <p>{t('exampleHint')}</p>
      {!exampleUrl ? <p>{t('notPublished')}</p> : <>
        {gpu !== undefined && gpu?.kind !== 'hardware' && <p>{t('requiresHardware')}</p>}
        <div className="flex flex-wrap gap-2">
          <button type="button" className={button} disabled={busy || gpu?.kind !== 'hardware'} onClick={() => void run()}>{t('run')}</button>
          {busy && <button type="button" className={button} onClick={() => controller.current?.abort()}>{t('cancel')}</button>}
        </div>
        {state.kind === 'loading' && <p role="status">{t('loading')}</p>}
        {state.kind === 'running' && <p role="status">{t('progress', state)}</p>}
        {state.kind === 'cancelled' && <p role="status">{t('cancelled')}</p>}
        {state.kind === 'error' && <p role="alert" className="text-red-300">{t('error')}</p>}
        {output && <CoarsePreview raster={output} />}
      </>}
    </div>
  </details>
}

function CoarsePreview({ raster }: { raster: ElevationRaster }) {
  const { t } = useTranslation('map', { keyPrefix: 'packs.compute' })
  const canvas = useRef<HTMLCanvasElement>(null)
  const { width, height, values } = raster
  useEffect(() => {
    const context = canvas.current?.getContext('2d')
    if (!context) return
    const image = context.createImageData(width, height)
    const min = Math.min(...values)
    const max = Math.max(...values)
    const colors = generateAdaptiveTerrainScale(min, max, 0)
    const bins = colors.length / 4 - 1
    values.forEach((value, index) => {
      const offset = 4 * Math.round(bins * (value - min) / (max - min || 1))
      image.data[index * 4] = colors[offset]
      image.data[index * 4 + 1] = colors[offset + 1]
      image.data[index * 4 + 2] = colors[offset + 2]
      image.data[index * 4 + 3] = 255
    })
    context.putImageData(image, 0, 0)
  }, [width, height, values])
  return <figure className="space-y-1">
    <canvas ref={canvas} width={width} height={height} className="h-auto w-full rounded [image-rendering:pixelated]"
      role="img" aria-label={t('previewLabel')} />
    <figcaption>{t('previewSize', { width, height })}</figcaption>
  </figure>
}
