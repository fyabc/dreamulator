/**
 * TemperatureLab — shared browser temperature experiment controls.
 *
 * Gate D of the Pyodide spike: load the engine's pure temperature functions in
 * the browser, take a heightmap (bundled Nacrea sample or a dropped PNG), and
 * render the annual / monthly temperature field on a regular lon/lat grid.
 *
 * Scope is deliberately narrow: no CVT mesh, no precipitation/wind/ocean,
 * no Köppen.  The page is a UI prototype for the eventual "upload heightmap →
 * climate layer" route, not a production world builder.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { getProject, projectsKey, saveTemperatureDraft, worldDataPath } from '../projects/projectStore'

import earthSample from './earth-180x90.json'
import earthHeightmap from './earth-180x90.png'
import nacreaSample from './nacrea-180x90.json'
import nacreaHeightmap from './nacrea-180x90.png'
import type { KernelResult, TemperatureResponse } from './temperature.worker'
import { temperatureRequest } from './temperatureRequest'
import { EARTH_PARAMS, GRID_W, GRID_H, MODEL_JANUARY_INDEX, isTemperatureParams, readTemperatureGrid,
  temperatureTrialReturnPath, type PlanetParams } from './temperatureDraft'
import { loadTemperatureElevation, temperatureInputCatalog, worldTemperatureParams } from './worldTemperature'
import { TEMPERATURE_GRADIENT, temperatureColor, type TemperaturePreview } from './temperaturePreview'

const CANVAS_W = 900
const CANVAS_H = 450

type Status = 'idle' | 'sample' | 'loading' | 'running'
type MonthSelection = 'annual' | number
type Sample = 'earth' | 'nacrea'
type LabError = { stage: 'sample' | 'world' | 'draft' | 'file' | 'runtime' | 'compute'; detail: string; sample?: Sample }

const NACREA_PARAMS: PlanetParams = {
  luminosity: 0.1227,
  distanceAu: 0.3648,
  albedo: 0.3,
  greenhouseK: 35,
  tiltDeg: 19.9,
  yearDays: 99.8196,
  rotationDays: 3.1336,
  seaLevelM: 0,
  elevMinM: -12116.5,
  elevMaxM: 9000,
  variableLapse: true,
}

const SAMPLES = {
  earth: { meta: earthSample, image: earthHeightmap, preset: EARTH_PARAMS },
  nacrea: { meta: nacreaSample, image: nacreaHeightmap, preset: NACREA_PARAMS },
}

function elevationFromGray(gray: Float32Array, p: PlanetParams): Float32Array {
  const span = p.elevMaxM - p.elevMinM
  const out = new Float32Array(gray.length)
  for (let i = 0; i < gray.length; i++) out[i] = p.elevMinM + gray[i] * span
  return out
}

async function decodeImageToGray(source: Blob | string): Promise<Float32Array> {
  const blob = typeof source === 'string'
    ? await fetch(source).then((r) => {
        if (!r.ok) throw new Error(`heightmap fetch ${r.status}`)
        return r.blob()
      })
    : source
  const bitmap = await createImageBitmap(blob)
  const canvas = document.createElement('canvas')
  canvas.width = GRID_W
  canvas.height = GRID_H
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('canvas 2d unavailable')
  ctx.drawImage(bitmap, 0, 0, GRID_W, GRID_H)
  const data = ctx.getImageData(0, 0, GRID_W, GRID_H).data
  const gray = new Float32Array(GRID_W * GRID_H)
  for (let i = 0; i < gray.length; i++) {
    const o = i * 4
    gray[i] = (data[o] + data[o + 1] + data[o + 2]) / 765
  }
  bitmap.close()
  return gray
}

function NumberField({
  label, value, step, min, max, onChange,
}: {
  label: string
  value: number
  step?: number
  min?: number
  max?: number
  onChange: (v: number) => void
}) {
  return (
    <label className="flex items-center justify-between gap-2 text-xs text-gray-300">
      <span>{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : ''}
        step={step ?? 'any'}
        min={min}
        max={max}
        onChange={(e) => onChange(e.target.valueAsNumber)}
        className="w-24 shrink-0 rounded border border-space-border bg-space-surface px-2 py-1.5 text-right text-sm tabular-nums text-gray-200 focus-visible:outline focus-visible:outline-neon-cyan"
      />
    </label>
  )
}

interface MapLab {
  onPreview: (preview: TemperaturePreview | null) => void
  onShowPreview: () => void
  showing: boolean
}

export default function TemperatureLab({ search, map }: { search: URLSearchParams; map?: MapLab }) {
  const world = search.get('world') || ''
  const planet = search.get('planet') || ''
  const branch = search.get('branch') || null
  const requestedDraft = search.get('draft') || null
  const from = search.get('from')
  const mapView = from === 'map' || from === 'globe' ? from : null
  const contextual = !!world && !!planet
  const { t } = useTranslation('playground')
  const { t: tMap } = useTranslation('map')
  const queryClient = useQueryClient()
  const modelMonths = tMap('months', { returnObjects: true }) as unknown as string[]
  const monthOptions = modelMonths.map((label, modelIndex) => ({ label, modelIndex }))
  const calendarMonths = [...monthOptions.slice(MODEL_JANUARY_INDEX), ...monthOptions.slice(0, MODEL_JANUARY_INDEX)]

  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<LabError | null>(null)
  const [loadSeconds, setLoadSeconds] = useState<number | null>(null)
  const [params, setParams] = useState<PlanetParams>(EARTH_PARAMS)
  const [gray, setGray] = useState<Float32Array | null>(null)
  const [heightmapName, setHeightmapName] = useState<string>('')
  const [result, setResult] = useState<KernelResult | null>(null)
  const [resultParams, setResultParams] = useState<PlanetParams | null>(null)
  const [selectedSample, setSelectedSample] = useState<Sample | null>(null)
  const [month, setMonth] = useState<MonthSelection>('annual')
  const [dragging, setDragging] = useState(false)
  const [bodyName, setBodyName] = useState(planet)
  const [usesDefaults, setUsesDefaults] = useState(false)
  const [draftId, setDraftId] = useState<string | null>(null)
  const [savedSnapshot, setSavedSnapshot] = useState<{ params: PlanetParams; gray: Float32Array } | null>(null)

  const workerRef = useRef<Worker | null>(null)
  const inputRequest = useRef(0)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const save = useMutation({
    mutationFn: async ({ id, grid, values }: { id: string; grid: Float32Array; values: PlanetParams }) => {
      await saveTemperatureDraft(world, { id, planet, branch, params: values, defaults: usesDefaults,
        source: heightmapName.slice(0, 200), updatedAt: Date.now(), grid: new Blob([new Float32Array(grid).buffer]) })
      return { id, params: values, gray: grid }
    },
    onSuccess: ({ id, params, gray }) => {
      setDraftId(id)
      setSavedSnapshot({ params, gray })
      void queryClient.invalidateQueries({ queryKey: projectsKey })
    },
  })

  // --- Heightmap sample ----------------------------------------------------
  const loadSample = useCallback(async (world: Sample) => {
    const request = ++inputRequest.current
    const { meta, image, preset } = SAMPLES[world]
    setStatus('sample')
    setError(null)
    try {
      const sampleGray = await decodeImageToGray(image)
      if (request !== inputRequest.current) return
      setGray(sampleGray)
      setHeightmapName(meta.name)
      setSelectedSample(world)
      setParams({
        ...preset,
        elevMinM: Math.round(meta.elevation_min_m * 10) / 10,
        elevMaxM: Math.round(meta.elevation_max_m * 10) / 10,
        seaLevelM: Math.round(meta.sea_level_m * 10) / 10,
      })
      setResult(null)
      setResultParams(null)
    } catch (err) {
      if (request === inputRequest.current) setError({ stage: 'sample', detail: String(err), sample: world })
    } finally {
      if (request === inputRequest.current) setStatus('idle')
    }
  }, [])

  const loadContext = useCallback(async () => {
    const request = ++inputRequest.current
    setStatus('sample')
    setError(null)
    try {
      if (requestedDraft) {
        const project = await getProject(world)
        const draft = project?.temperatureDrafts?.find(item => item.id === requestedDraft && item.planet === planet && item.branch === branch)
        if (!draft) throw new Error('Temperature draft is missing')
        const values = await readTemperatureGrid(draft.grid)
        if (request !== inputRequest.current) return
        setParams(draft.params)
        setGray(values)
        setHeightmapName(draft.source)
        setUsesDefaults(draft.defaults)
        setDraftId(draft.id)
        setSavedSnapshot({ params: draft.params, gray: values })
        return
      }
      let catalog = await api.getSystemCatalog(world, branch).catch(() => null)
      if (!catalog?.bodies?.some(body => body.id === planet)) {
        const [stellar, planets] = await Promise.all([
          api.getStellarSystem(world, branch).catch(() => null), api.getPlanets(world, branch).catch(() => []),
        ])
        catalog = temperatureInputCatalog(stellar, planets)
      }
      const settings = worldTemperatureParams(catalog, planet)
      if (request !== inputRequest.current) return
      setBodyName(settings.name)
      setUsesDefaults(settings.defaults)
      setParams(settings.params)
      const [meta, blob] = await Promise.all([api.getMapMeta(world, planet, branch), api.getElevationBlob(world, planet, branch)])
      const { gray: values, ...mapping } = await loadTemperatureElevation(blob, meta)
      if (request !== inputRequest.current) return
      setGray(values)
      setParams({ ...settings.params, ...mapping })
      setHeightmapName(`${world} · ${settings.name}${branch ? ` · ${branch}` : ''}`)
    } catch (err) {
      if (request === inputRequest.current) setError({ stage: requestedDraft ? 'draft' : 'world', detail: String(err) })
    } finally {
      if (request === inputRequest.current) setStatus('idle')
    }
  }, [world, planet, branch, requestedDraft])

  useEffect(() => {
    if (contextual) void loadContext()
    else void loadSample('earth')
    return () => {
      inputRequest.current += 1
      workerRef.current?.terminate()
      workerRef.current = null
    }
  }, [contextual, loadContext, loadSample])

  // --- Compute -------------------------------------------------------------
  const validParams = isTemperatureParams(params)
  const run = () => {
    if (!gray || !validParams || status !== 'idle') return
    setError(null)
    try {
      const worker = workerRef.current ?? new Worker(
        new URL('./temperature.worker.ts', import.meta.url), { type: 'module' },
      )
      setStatus(workerRef.current ? 'running' : 'loading')
      workerRef.current = worker
      const handleFailure = (stage: 'runtime' | 'compute', detail: string) => {
        if (stage === 'runtime') {
          worker.terminate()
          workerRef.current = null
          setLoadSeconds(null)
        }
        setError({ stage, detail })
        setStatus('idle')
      }
      worker.onerror = event => handleFailure('runtime', event.message)
      worker.onmessage = ({ data }: MessageEvent<TemperatureResponse>) => {
        if (data.type === 'runtime-ready') {
          setLoadSeconds(data.seconds)
          setStatus('running')
        } else if (data.type === 'result') {
          setResult(data.result)
          setResultParams(params)
          setMonth('annual')
          setStatus('idle')
          map?.onShowPreview()
        } else {
          handleFailure(data.stage, data.detail)
        }
      }
      const elev = elevationFromGray(gray, params)
      worker.postMessage(temperatureRequest(elev, params), [elev.buffer])
    } catch (err) {
      workerRef.current?.terminate()
      workerRef.current = null
      setLoadSeconds(null)
      setError({ stage: 'runtime', detail: String(err) })
      setStatus('idle')
    }
  }

  // --- Canvas painting -----------------------------------------------------
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, CANVAS_W, CANVAS_H)
    if (!gray) {
      ctx.fillStyle = '#0a0a1a'
      ctx.fillRect(0, 0, CANVAS_W, CANVAS_H)
      return
    }

    const off = document.createElement('canvas')
    off.width = GRID_W
    off.height = GRID_H
    const offCtx = off.getContext('2d')
    if (!offCtx) return

    // Before the first temperature run, show the imported heightmap itself so
    // the user can confirm which file is loaded.
    if (!result || !resultParams) {
      const img = offCtx.createImageData(GRID_W, GRID_H)
      for (let i = 0; i < gray.length; i++) {
        const v = Math.round(Math.max(0, Math.min(1, gray[i])) * 255)
        img.data[i * 4] = v
        img.data[i * 4 + 1] = v
        img.data[i * 4 + 2] = v
        img.data[i * 4 + 3] = 255
      }
      offCtx.putImageData(img, 0, 0)
      ctx.imageSmoothingEnabled = true
      ctx.drawImage(off, 0, 0, CANVAS_W, CANVAS_H)
      return
    }

    const field = month === 'annual' ? result.annual : result.monthly[month]
    const img = offCtx.createImageData(GRID_W, GRID_H)
    for (let i = 0; i < field.length; i++) {
      const [r, g, b] = temperatureColor(field[i])
      img.data[i * 4] = r
      img.data[i * 4 + 1] = g
      img.data[i * 4 + 2] = b
      img.data[i * 4 + 3] = 255
    }
    offCtx.putImageData(img, 0, 0)

    ctx.imageSmoothingEnabled = true
    ctx.drawImage(off, 0, 0, CANVAS_W, CANVAS_H)

    // Coastline: cell edges where the land mask changes.
    const elev = elevationFromGray(gray, resultParams)
    const sx = CANVAS_W / GRID_W
    const sy = CANVAS_H / GRID_H
    ctx.strokeStyle = 'rgba(8, 12, 22, 0.28)'
    ctx.lineWidth = 0.7
    ctx.beginPath()
    for (let y = 0; y < GRID_H; y++) {
      for (let x = 0; x < GRID_W; x++) {
        const i = y * GRID_W + x
        const land = elev[i] > resultParams.seaLevelM
        if (x + 1 < GRID_W && (elev[i + 1] > resultParams.seaLevelM) !== land) {
          ctx.moveTo((x + 1) * sx, y * sy)
          ctx.lineTo((x + 1) * sx, (y + 1) * sy)
        }
        if (y + 1 < GRID_H && (elev[i + GRID_W] > resultParams.seaLevelM) !== land) {
          ctx.moveTo(x * sx, (y + 1) * sy)
          ctx.lineTo((x + 1) * sx, (y + 1) * sy)
        }
      }
    }
    ctx.stroke()
  }, [gray, month, result, resultParams])

  // --- Drag/drop / file input ---------------------------------------------
  const acceptFile = useCallback(async (file: File | undefined) => {
    if (!file) return
    const request = ++inputRequest.current
    setStatus('sample')
    setError(null)
    try {
      const next = await decodeImageToGray(file)
      if (request !== inputRequest.current) return
      setGray(next)
      setHeightmapName(file.name)
      setSelectedSample(null)
      setResult(null)
      setResultParams(null)
    } catch (err) {
      if (request === inputRequest.current) setError({ stage: 'file', detail: String(err) })
    } finally {
      if (request === inputRequest.current) setStatus('idle')
    }
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (status === 'idle') void acceptFile(e.dataTransfer.files?.[0])
  }, [acceptFile, status])

  const stats = useMemo(() => {
    if (!result) return null
    return [
      { label: t('stats.globalMean'), value: `${result.globalMeanC.toFixed(1)} °C` },
      { label: t('stats.areaMean'), value: `${result.annualMeanC.toFixed(1)} °C` },
      { label: t('stats.range'), value: `${result.minC.toFixed(0)} … ${result.maxC.toFixed(0)} °C` },
      { label: t('stats.computeTime'), value: `${result.elapsedS.toFixed(2)} s` },
    ]
  }, [result, t])

  const busy = status !== 'idle'
  const failedSample = error?.sample
  const sourceLabel = selectedSample === 'earth' ? t('params.presetEarth') : heightmapName
  const saved = savedSnapshot?.params === params && savedSnapshot.gray === gray
  const backTo = temperatureTrialReturnPath({ world, planet, branch }, search)
  const stale = resultParams != null && (Object.keys(params) as Array<keyof PlanetParams>)
    .some(key => params[key] !== resultParams[key])
  const phase = status === 'sample' ? t('action.loadingInput')
    : status === 'loading' ? t('action.loadingEngine')
      : status === 'running' ? t('action.computing') : ''
  const reportPreview = map?.onPreview
  const monthLabel = month === 'annual' ? t('view.annual') : modelMonths[month]
  const field = result && (month === 'annual' ? result.annual : result.monthly[month])
  useEffect(() => {
    reportPreview?.(field ? { field, label: monthLabel, stale } : null)
  }, [field, monthLabel, stale, reportPreview])

  const monthSelect = (
    <select aria-label={t('view.month')} value={month}
      onChange={(event) => setMonth(event.target.value === 'annual' ? 'annual' : Number(event.target.value))}
      className="rounded-md border border-space-border bg-space-surface px-2 py-1.5 text-xs text-gray-200 focus-visible:outline focus-visible:outline-neon-cyan">
      <option value="annual">{t('view.annual')}</option>
      {calendarMonths.map(({ label, modelIndex }) => <option key={modelIndex} value={modelIndex}>{label}</option>)}
    </select>
  )
  const controls = (
        <aside className={map ? 'space-y-2' : 'space-y-4'}>
          {!map && (
          <section className="rounded-xl border border-space-border bg-space-panel/60 p-4">
            <h2 className="font-semibold text-gray-100">{t('heightmap.title')}</h2>
            <p className="mt-1 text-xs text-gray-400">{t(contextual ? mapView ? 'trial.mapSourceHelp' : 'trial.sourceHelp' : 'heightmap.start')}</p>
            {!contextual && <div className="my-3 flex flex-wrap gap-2">
              {(['earth', 'nacrea'] as const).map(sample => (
                <button
                  key={sample}
                  type="button"
                  disabled={busy}
                  aria-pressed={selectedSample === sample}
                  onClick={() => void loadSample(sample)}
                  className="rounded-md border border-space-border px-3 py-2 text-xs text-gray-200 hover:border-neon-cyan/50 focus-visible:outline focus-visible:outline-neon-cyan aria-pressed:border-neon-cyan/50 aria-pressed:bg-neon-cyan/10 aria-pressed:text-neon-cyan disabled:opacity-60"
                >
                  {t(sample === 'earth' ? 'heightmap.sampleEarth' : 'heightmap.sampleNacrea')}
                </button>
              ))}
            </div>}
            <button
              type="button"
              disabled={busy}
              onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`mt-2 w-full rounded-lg border border-dashed p-3 text-left text-xs leading-relaxed transition-colors focus-visible:outline focus-visible:outline-neon-cyan disabled:opacity-60 ${
                dragging ? 'border-neon-cyan bg-neon-cyan/10 text-neon-cyan' : 'border-space-border text-gray-300 hover:border-neon-cyan/40'
              }`}
            >
              {t('heightmap.drop')}
            </button>
            <p className="mt-2 text-xs leading-relaxed text-gray-400">{t('heightmap.hint')}</p>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(e) => { void acceptFile(e.target.files?.[0]); e.target.value = '' }}
            />
          </section>
          )}

          <section aria-label={t('params.title')} className={map ? undefined : 'rounded-xl border border-space-border bg-space-panel/60 p-4'}>
            {!map && <h2 className="mb-3 font-semibold text-gray-100">{t('params.title')}</h2>}
            {usesDefaults && <p className="mb-3 text-xs leading-relaxed text-amber-200">{t('trial.defaults')}</p>}
            <fieldset disabled={busy} className="min-w-0 space-y-2 disabled:opacity-60">
              <NumberField label={t('params.albedo')} value={params.albedo} step={0.001} min={0} max={1} onChange={(v) => setParams((p) => ({ ...p, albedo: v }))} />
              <NumberField label={t('params.greenhouse')} value={params.greenhouseK} step={0.5} min={0} onChange={(v) => setParams((p) => ({ ...p, greenhouseK: v }))} />
              <NumberField label={t('params.tilt')} value={params.tiltDeg} step={0.1} min={0} max={90} onChange={(v) => setParams((p) => ({ ...p, tiltDeg: v }))} />
              <details className="border-t border-space-border pt-2">
                <summary className="cursor-pointer rounded py-1 text-sm text-gray-300 hover:text-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan">{t('params.advanced')}</summary>
                <div className="mt-2 space-y-2">
                  <NumberField label={t('params.luminosity')} value={params.luminosity} step={0.001} min={0} onChange={(v) => setParams((p) => ({ ...p, luminosity: v }))} />
                  <NumberField label={t('params.distance')} value={params.distanceAu} step={0.001} min={0.001} onChange={(v) => setParams((p) => ({ ...p, distanceAu: v }))} />
                  <NumberField label={t('params.year')} value={params.yearDays} step={0.1} min={0.1} onChange={(v) => setParams((p) => ({ ...p, yearDays: v }))} />
                  <NumberField label={t('params.rotation')} value={params.rotationDays} step={0.01} min={0.01} onChange={(v) => setParams((p) => ({ ...p, rotationDays: v }))} />
                  <NumberField label={t('params.seaLevel')} value={params.seaLevelM} step={10} onChange={(v) => setParams((p) => ({ ...p, seaLevelM: v }))} />
                  <NumberField label={t('params.elevMin')} value={params.elevMinM} step={10} onChange={(v) => setParams((p) => ({ ...p, elevMinM: v }))} />
                  <NumberField label={t('params.elevMax')} value={params.elevMaxM} step={10} onChange={(v) => setParams((p) => ({ ...p, elevMaxM: v }))} />
                  <label className="flex items-center gap-2 text-xs text-gray-300">
                    <input type="checkbox" checked={params.variableLapse} onChange={(e) => setParams((p) => ({ ...p, variableLapse: e.target.checked }))} className="h-4 w-4 accent-neon-cyan" />
                    {t('params.variableLapse')}
                  </label>
                </div>
              </details>
            </fieldset>
          </section>

          <button
            type="button"
            onClick={run}
            disabled={busy || !gray || !validParams}
            className="w-full rounded-lg border border-neon-cyan/40 bg-neon-cyan/15 px-3 py-2 text-sm font-medium text-neon-cyan transition-colors hover:bg-neon-cyan/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {phase || (error?.stage === 'runtime' || error?.stage === 'compute'
              ? t('action.retryRun') : result ? t('action.recompute') : t('action.run'))}
          </button>
          {contextual && <div className="space-y-2 text-xs leading-relaxed text-gray-400">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <button type="button" disabled={busy || !gray || !validParams || save.isPending || saved}
                className="min-h-10 rounded border border-space-border px-3 text-gray-200 hover:border-neon-cyan disabled:opacity-50"
                onClick={() => { if (gray) save.mutate({ id: draftId ?? crypto.randomUUID(), grid: gray, values: params }) }}>
                {t(save.isPending ? 'trial.saving' : saved ? 'trial.saved' : 'trial.save')}
              </button>
              {draftId && <Link to={worldDataPath(world, branch)} className="text-neon-cyan hover:underline">{t('trial.openData')}</Link>}
            </div>
            <p>{t('trial.saveHelp')}</p>
            {save.isError && <p role="alert" className="text-red-300">{t('trial.saveError')}</p>}
          </div>}

          <p role="status" className="text-xs leading-relaxed text-gray-400 empty:hidden">
            {phase || (loadSeconds != null ? t('status.engineLoaded', { seconds: loadSeconds.toFixed(1) }) : '')}
          </p>
          {!validParams && <p role="alert" className="text-xs text-amber-200">{t('error.params')}</p>}
          {error && (
            <div className="border-l-2 border-red-400/70 pl-3 text-xs leading-relaxed text-red-200">
              <p role="alert">{t(`error.${error.stage}`)}</p>
              {failedSample && <button type="button" className="my-1 text-neon-cyan underline" onClick={() => void loadSample(failedSample)}>{t('action.retrySample')}</button>}
              {(error.stage === 'world' || error.stage === 'draft') && <button type="button"
                className="my-1 text-neon-cyan underline" onClick={() => void loadContext()}>{t('trial.retry')}</button>}
              <details className="mt-1 text-gray-400">
                <summary className="cursor-pointer">{t('error.details')}</summary>
                <p className="max-h-32 overflow-auto whitespace-pre-wrap break-words">{error.detail}</p>
              </details>
            </div>
          )}
        </aside>
  )

  if (map) return (
    <div className="space-y-2">
      <p className="text-xs leading-relaxed text-gray-400">{t('trial.inlineSourceHelp')}</p>
      {result && <div className="flex flex-wrap items-center justify-between gap-2 border-b border-space-border pb-2">
        {monthSelect}
        {!map.showing && <button type="button" onClick={map.onShowPreview} className="atlas-tool-button text-xs">{t('trial.showPreview')}</button>}
      </div>}
      {controls}
    </div>
  )

  return (
    <div className="mx-auto max-w-7xl px-4 py-4 md:px-6 md:py-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-neon-cyan neon-glow-subtle">{t(contextual ? 'trial.title' : 'title')}</h1>
            <span className="rounded border border-amber-400/40 bg-amber-400/10 px-1.5 py-0.5 text-[10px] text-amber-200">
              {t('badge')}
            </span>
          </div>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-gray-400">{t(contextual ? 'trial.subtitle' : 'subtitle')}</p>
          {contextual && <p className="mt-2 break-words text-sm text-gray-200">
            {world} · {bodyName} · {branch || t('trial.root')}
          </p>}
        </div>
        <Link to={backTo} className="text-sm text-gray-400 hover:text-neon-cyan">{t(contextual ? mapView ? 'trial.backMap' : 'trial.backClimate' : 'trial.backHelp')}</Link>
      </div>

      <div className="grid items-start gap-4 lg:grid-cols-[310px,minmax(0,1fr)] xl:grid-cols-[340px,minmax(0,1fr)]">
        {controls}

        {/* Preview */}
        <section className="space-y-3">
          <div className="rounded-xl border border-space-border bg-space-panel/60 p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                  {result ? t('view.title') : t('view.heightmapPreview')}
                </h2>
              </div>
              {result && monthSelect}
            </div>
            {gray && <p className="mb-2 break-words text-xs text-gray-400">{t('stats.gridInfo', { name: sourceLabel, width: GRID_W, height: GRID_H })}</p>}

            {stale && <p role="status" className="mb-2 border-l-2 border-amber-400/70 pl-2 text-xs text-amber-200">{t('status.previousResult')}</p>}

            <canvas
              ref={canvasRef}
              role="img"
              aria-label={result ? t('view.title') : t('view.heightmapPreview')}
              width={CANVAS_W}
              height={CANVAS_H}
              className="w-full rounded-lg border border-space-border bg-[#0a0a1a]"
              style={{ aspectRatio: '2 / 1' }}
            />

            {result && (
              <div className="mt-2 flex items-center gap-2 text-[10px] text-gray-500">
                <span>-40 °C</span>
                <div
                  className="h-2 flex-1 rounded"
                  style={{ background: TEMPERATURE_GRADIENT }}
                />
                <span>+40 °C</span>
              </div>
            )}

            {!result && (
              <div className="mt-3 rounded-lg border border-space-border bg-space-surface/60 p-3 text-xs leading-relaxed text-gray-500">
                {t('view.placeholder')}
              </div>
            )}
          </div>
          <p className="text-xs leading-relaxed text-gray-400">{t('note')}</p>

          {stats && (
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {stats.map((s) => (
                <div key={s.label} className="rounded-lg border border-space-border bg-space-panel/50 p-2">
                  <div className="text-[10px] text-gray-500">{s.label}</div>
                  <div className="text-sm font-medium tabular-nums text-gray-200">{s.value}</div>
                </div>
              ))}
            </div>
          )}

        </section>
      </div>
    </div>
  )
}
