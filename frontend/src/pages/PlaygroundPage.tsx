/**
 * PlaygroundPage — experimental, server-less "temperature first image" demo.
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

import climatePhysicsSrc from '../../../src/dreamulator/engine/climate_physics.py?raw'
import climateSeasonalitySrc from '../../../src/dreamulator/engine/climate_seasonality.py?raw'
import temperatureKernelSrc from '../playground/temperature_kernel.py?raw'

// Pyodide 314.x uses the `v314.0.7` distribution path on jsDelivr.
const PYODIDE_VERSION = '314.0.7'
const PYODIDE_BASE = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`

const GRID_W = 180
const GRID_H = 90
const CANVAS_W = 900
const CANVAS_H = 450

type Status = 'idle' | 'loading' | 'ready' | 'running' | 'error'
type MonthSelection = 'annual' | number

interface PlanetParams {
  luminosity: number
  distanceAu: number
  albedo: number
  greenhouseK: number
  tiltDeg: number
  yearDays: number
  rotationDays: number
  seaLevelM: number
  elevMinM: number
  elevMaxM: number
  variableLapse: boolean
}

interface KernelResult {
  annual: number[]
  monthly: number[][]
  latDeg: number[]
  globalMeanC: number
  annualMeanC: number
  minC: number
  maxC: number
  elapsedS: number
}

interface SampleMeta {
  name: string
  width: number
  height: number
  elevation_min_m: number
  elevation_max_m: number
  sea_level_m: number
}

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

const EARTH_PARAMS: PlanetParams = {
  luminosity: 1,
  distanceAu: 1,
  albedo: 0.306,
  greenhouseK: 33,
  tiltDeg: 23.44,
  yearDays: 365.25,
  rotationDays: 1,
  seaLevelM: 0,
  elevMinM: -11000,
  elevMaxM: 9000,
  variableLapse: true,
}

/** RdYlBu-ish temperature ramp, °C. */
const TEMP_STOPS: Array<[number, [number, number, number]]> = [
  [-40, [49, 54, 149]],
  [-20, [69, 117, 180]],
  [0, [255, 255, 191]],
  [20, [253, 174, 97]],
  [40, [165, 0, 38]],
]

function temperatureColor(t: number): [number, number, number] {
  const clamped = Math.max(-40, Math.min(40, t))
  for (let i = 1; i < TEMP_STOPS.length; i++) {
    const [t1, c1] = TEMP_STOPS[i]
    const [t0, c0] = TEMP_STOPS[i - 1]
    if (clamped <= t1) {
      const u = (clamped - t0) / (t1 - t0)
      return [
        Math.round(c0[0] + (c1[0] - c0[0]) * u),
        Math.round(c0[1] + (c1[1] - c0[1]) * u),
        Math.round(c0[2] + (c1[2] - c0[2]) * u),
      ]
    }
  }
  return TEMP_STOPS[TEMP_STOPS.length - 1][1]
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
    <label className="flex items-center justify-between gap-2 text-[11px] text-gray-400">
      <span className="min-w-0 truncate">{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        step={step ?? 0.01}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-24 shrink-0 rounded border border-space-border bg-space-surface px-1.5 py-0.5 text-right text-[11px] text-gray-200"
      />
    </label>
  )
}

export default function PlaygroundPage() {
  const { t } = useTranslation('playground')
  const { t: tMap } = useTranslation('map')
  const months = tMap('months', { returnObjects: true }) as unknown as string[]

  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<string | null>(null)
  const [loadSeconds, setLoadSeconds] = useState<number | null>(null)
  const [params, setParams] = useState<PlanetParams>(EARTH_PARAMS)
  const [gray, setGray] = useState<Float32Array | null>(null)
  const [heightmapName, setHeightmapName] = useState<string>('')
  const [sampleMeta, setSampleMeta] = useState<SampleMeta | null>(null)
  const [result, setResult] = useState<KernelResult | null>(null)
  const [month, setMonth] = useState<MonthSelection>('annual')
  const [dragging, setDragging] = useState(false)

  const pyRef = useRef<any>(null)
  const pyPromiseRef = useRef<Promise<any> | null>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // --- Heightmap sample ----------------------------------------------------
  const loadSample = useCallback(async (world: 'earth' | 'nacrea') => {
    try {
      const base = import.meta.env.BASE_URL
      const meta = await fetch(`${base}playground/${world}-180x90.json`).then((r) => {
        if (!r.ok) throw new Error(`sample meta ${r.status}`)
        return r.json() as Promise<SampleMeta>
      })
      const sampleGray = await decodeImageToGray(`${base}playground/${world}-180x90.png`)
      const preset = world === 'earth' ? EARTH_PARAMS : NACREA_PARAMS
      setSampleMeta(meta)
      setGray(sampleGray)
      setHeightmapName(meta.name)
      setParams({
        ...preset,
        elevMinM: Math.round(meta.elevation_min_m * 10) / 10,
        elevMaxM: Math.round(meta.elevation_max_m * 10) / 10,
        seaLevelM: Math.round(meta.sea_level_m * 10) / 10,
      })
      setResult(null)
      setStatus(pyRef.current ? 'ready' : 'idle')
      setError(null)
    } catch (err) {
      setError(String(err))
      setStatus('error')
    }
  }, [])

  useEffect(() => {
    void loadSample('earth')
  }, [loadSample])

  // --- Pyodide bootstrap ---------------------------------------------------
  const ensurePyodide = useCallback(async () => {
    if (pyRef.current) return pyRef.current
    if (pyPromiseRef.current) return pyPromiseRef.current

    const promise = (async () => {
      setStatus('loading')
      setError(null)
      const t0 = performance.now()
      const mod = await import(/* @vite-ignore */ `${PYODIDE_BASE}pyodide.mjs`)
      const loadPyodide = mod.loadPyodide ?? mod.default?.loadPyodide
      if (!loadPyodide) throw new Error('pyodide loader missing')
      const py = await loadPyodide({ indexURL: PYODIDE_BASE })
      await py.loadPackage('numpy')

      for (const path of ['/engine', '/engine/dreamulator', '/engine/dreamulator/engine', '/kernel']) {
        try { py.FS.mkdir(path) } catch { /* already exists */ }
      }
      py.FS.writeFile('/engine/dreamulator/__init__.py', '')
      py.FS.writeFile('/engine/dreamulator/engine/__init__.py', '')
      py.FS.writeFile('/engine/dreamulator/engine/climate_physics.py', climatePhysicsSrc)
      py.FS.writeFile('/engine/dreamulator/engine/climate_seasonality.py', climateSeasonalitySrc)
      py.FS.writeFile('/kernel/temperature_kernel.py', temperatureKernelSrc)
      await py.runPythonAsync(`
import sys
sys.path.insert(0, '/engine')
sys.path.insert(0, '/kernel')
from temperature_kernel import compute_temperature
`)
      pyRef.current = py
      setLoadSeconds((performance.now() - t0) / 1000)
      setStatus('ready')
      return py
    })()

    pyPromiseRef.current = promise
    try {
      return await promise
    } catch (err) {
      pyPromiseRef.current = null
      setError(String(err))
      setStatus('error')
      throw err
    }
  }, [])

  // --- Compute -------------------------------------------------------------
  const run = useCallback(async () => {
    if (!gray) {
      setError(t('error.noHeightmap'))
      return
    }
    try {
      const py = await ensurePyodide()
      setStatus('running')
      setError(null)
      const elev = elevationFromGray(gray, params)
      const payload = {
        width: GRID_W,
        height: GRID_H,
        sea_level_m: params.seaLevelM,
        stellar_luminosity_sol: params.luminosity,
        orbital_distance_au: params.distanceAu,
        albedo: params.albedo,
        greenhouse_warming_K: params.greenhouseK,
        axial_tilt_deg: params.tiltDeg,
        orbital_period_days: params.yearDays,
        rotation_period_days: params.rotationDays,
        variable_lapse_rate: params.variableLapse,
      }
      py.globals.set('elev_json', JSON.stringify(Array.from(elev)))
      py.globals.set('params_json', JSON.stringify(payload))
      const raw = py.runPython('compute_temperature(elev_json, params_json)')
      const parsed = JSON.parse(typeof raw === 'string' ? raw : String(raw)) as KernelResult
      setResult(parsed)
      setMonth('annual')
      setStatus('ready')
    } catch (err) {
      setError(String(err))
      setStatus('error')
    }
  }, [ensurePyodide, gray, params, t])

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
    if (!result) {
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
    const elev = elevationFromGray(gray, params)
    const sx = CANVAS_W / GRID_W
    const sy = CANVAS_H / GRID_H
    ctx.strokeStyle = 'rgba(8, 12, 22, 0.28)'
    ctx.lineWidth = 0.7
    ctx.beginPath()
    for (let y = 0; y < GRID_H; y++) {
      for (let x = 0; x < GRID_W; x++) {
        const i = y * GRID_W + x
        const land = elev[i] > params.seaLevelM
        if (x + 1 < GRID_W && (elev[i + 1] > params.seaLevelM) !== land) {
          ctx.moveTo((x + 1) * sx, y * sy)
          ctx.lineTo((x + 1) * sx, (y + 1) * sy)
        }
        if (y + 1 < GRID_H && (elev[i + GRID_W] > params.seaLevelM) !== land) {
          ctx.moveTo(x * sx, (y + 1) * sy)
          ctx.lineTo((x + 1) * sx, (y + 1) * sy)
        }
      }
    }
    ctx.stroke()
  }, [gray, month, params.elevMaxM, params.elevMinM, params.seaLevelM, result])

  // --- Drag/drop / file input ---------------------------------------------
  const acceptFile = useCallback(async (file: File | undefined) => {
    if (!file) return
    try {
      const next = await decodeImageToGray(file)
      setGray(next)
      setHeightmapName(file.name)
      setResult(null)
      setStatus(pyRef.current ? 'ready' : 'idle')
      setError(null)
    } catch (err) {
      setError(String(err))
      setStatus('error')
    }
  }, [])

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    void acceptFile(e.dataTransfer.files?.[0])
  }, [acceptFile])

  const applyPreset = useCallback((preset: 'nacrea' | 'earth') => {
    setParams((p) => ({
      ...(preset === 'nacrea' ? NACREA_PARAMS : EARTH_PARAMS),
      elevMinM: p.elevMinM,
      elevMaxM: p.elevMaxM,
      seaLevelM: p.seaLevelM,
    }))
    setResult(null)
  }, [])

  const monthLabel = month === 'annual'
    ? t('view.annual')
    : `${t('view.month')} ${months[month] ?? month + 1}`

  const stats = useMemo(() => {
    if (!result) return null
    return [
      { label: t('stats.globalMean'), value: `${result.globalMeanC.toFixed(1)} °C` },
      { label: t('stats.areaMean'), value: `${result.annualMeanC.toFixed(1)} °C` },
      { label: t('stats.range'), value: `${result.minC.toFixed(0)} … ${result.maxC.toFixed(0)} °C` },
      { label: t('stats.computeTime'), value: `${result.elapsedS.toFixed(2)} s` },
    ]
  }, [result, t])

  const busy = status === 'loading' || status === 'running'

  return (
    <div className="mx-auto max-w-7xl px-4 py-4 md:px-6 md:py-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold text-neon-cyan neon-glow-subtle">{t('title')}</h1>
            <span className="rounded border border-amber-400/40 bg-amber-400/10 px-1.5 py-0.5 text-[10px] text-amber-200">
              {t('badge')}
            </span>
          </div>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-gray-500">{t('subtitle')}</p>
        </div>
        <Link to="/worlds" className="text-sm text-gray-400 hover:text-neon-cyan">{t('back')}</Link>
      </div>

      <div className="grid gap-4 lg:grid-cols-[330px,minmax(0,1fr)]">
        {/* Controls */}
        <aside className="space-y-4">
          <section className="rounded-xl border border-space-border bg-space-panel/60 p-3">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">{t('params.title')}</h2>
              <div className="flex gap-1">
                <button
                  type="button"
                  onClick={() => applyPreset('earth')}
                  className="rounded border border-space-border px-1.5 py-0.5 text-[10px] text-gray-400 hover:text-neon-cyan"
                >
                  {t('params.presetEarth')}
                </button>
                <button
                  type="button"
                  onClick={() => applyPreset('nacrea')}
                  className="rounded border border-space-border px-1.5 py-0.5 text-[10px] text-gray-400 hover:text-neon-cyan"
                >
                  {t('params.presetNacrea')}
                </button>
              </div>
            </div>
            <div className="space-y-1.5">
              <NumberField label={t('params.luminosity')} value={params.luminosity} step={0.001} min={0} onChange={(v) => setParams((p) => ({ ...p, luminosity: v }))} />
              <NumberField label={t('params.distance')} value={params.distanceAu} step={0.001} min={0.001} onChange={(v) => setParams((p) => ({ ...p, distanceAu: v }))} />
              <NumberField label={t('params.albedo')} value={params.albedo} step={0.001} min={0} max={1} onChange={(v) => setParams((p) => ({ ...p, albedo: v }))} />
              <NumberField label={t('params.greenhouse')} value={params.greenhouseK} step={0.5} min={0} onChange={(v) => setParams((p) => ({ ...p, greenhouseK: v }))} />
              <NumberField label={t('params.tilt')} value={params.tiltDeg} step={0.1} min={0} max={90} onChange={(v) => setParams((p) => ({ ...p, tiltDeg: v }))} />
              <NumberField label={t('params.year')} value={params.yearDays} step={0.1} min={0.1} onChange={(v) => setParams((p) => ({ ...p, yearDays: v }))} />
              <NumberField label={t('params.rotation')} value={params.rotationDays} step={0.01} min={0.01} onChange={(v) => setParams((p) => ({ ...p, rotationDays: v }))} />
              <NumberField label={t('params.seaLevel')} value={params.seaLevelM} step={10} onChange={(v) => setParams((p) => ({ ...p, seaLevelM: v }))} />
              <NumberField label={t('params.elevMin')} value={params.elevMinM} step={10} onChange={(v) => setParams((p) => ({ ...p, elevMinM: v }))} />
              <NumberField label={t('params.elevMax')} value={params.elevMaxM} step={10} onChange={(v) => setParams((p) => ({ ...p, elevMaxM: v }))} />
              <label className="flex items-center gap-2 text-[11px] text-gray-400">
                <input
                  type="checkbox"
                  checked={params.variableLapse}
                  onChange={(e) => setParams((p) => ({ ...p, variableLapse: e.target.checked }))}
                  className="h-3 w-3 accent-neon-cyan"
                />
                {t('params.variableLapse')}
              </label>
            </div>
          </section>

          <section className="rounded-xl border border-space-border bg-space-panel/60 p-3">
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-400">{t('heightmap.title')}</h2>
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`cursor-pointer rounded-lg border border-dashed p-3 text-center text-[11px] leading-relaxed transition-colors ${
                dragging ? 'border-neon-cyan bg-neon-cyan/10 text-neon-cyan' : 'border-space-border text-gray-500 hover:border-neon-cyan/40'
              }`}
            >
              <div className="mb-1 text-lg">🗺️</div>
              <div>{t('heightmap.drop')}</div>
              <div className="mt-1 text-[10px] text-gray-600">{t('heightmap.hint')}</div>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(e) => { void acceptFile(e.target.files?.[0]); e.target.value = '' }}
            />
            <div className="mt-2 flex items-center justify-between gap-2 text-[10px] text-gray-500">
              <span className="truncate" title={heightmapName}>{heightmapName || t('heightmap.none')}</span>
              <div className="flex shrink-0 gap-2">
                <button type="button" onClick={() => void loadSample('earth')} className="text-neon-cyan/80 hover:text-neon-cyan">
                  {t('heightmap.sampleEarth')}
                </button>
                <button type="button" onClick={() => void loadSample('nacrea')} className="text-neon-cyan/80 hover:text-neon-cyan">
                  {t('heightmap.sampleNacrea')}
                </button>
              </div>
            </div>
          </section>

          <button
            type="button"
            onClick={() => void run()}
            disabled={busy || !gray}
            className="w-full rounded-lg border border-neon-cyan/40 bg-neon-cyan/15 px-3 py-2 text-sm font-medium text-neon-cyan transition-colors hover:bg-neon-cyan/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {status === 'loading'
              ? t('action.loadingEngine')
              : status === 'running'
                ? t('action.computing')
                : result ? t('action.recompute') : t('action.run')}
          </button>

          <div className="text-[10px] leading-relaxed text-gray-600">
            {loadSeconds != null && <div>{t('status.engineLoaded', { seconds: loadSeconds.toFixed(1) })}</div>}
            {status === 'error' && <div className="text-red-400">{error}</div>}
            {status !== 'error' && error && <div className="text-red-400">{error}</div>}
            <div className="mt-1">{t('note')}</div>
          </div>
        </aside>

        {/* Preview */}
        <section className="space-y-3">
          <div className="rounded-xl border border-space-border bg-space-panel/60 p-3">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <h2 className="text-xs font-semibold uppercase tracking-wide text-gray-400">
                  {result ? t('view.title') : t('view.heightmapPreview')}
                </h2>
                <span className="text-[10px] text-gray-500">{GRID_W}×{GRID_H}</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setMonth('annual')}
                  className={`rounded px-2 py-0.5 text-[11px] ${month === 'annual' ? 'bg-neon-cyan/20 text-neon-cyan' : 'text-gray-500 hover:text-gray-300'}`}
                >
                  {t('view.annual')}
                </button>
                <input
                  type="range"
                  min={0}
                  max={11}
                  step={1}
                  value={month === 'annual' ? 0 : month}
                  disabled={!result}
                  onChange={(e) => setMonth(parseInt(e.target.value))}
                  className="w-24 accent-neon-cyan disabled:opacity-40"
                />
                <span className="w-20 text-right text-[10px] text-gray-400">{monthLabel}</span>
              </div>
            </div>

            <canvas
              ref={canvasRef}
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
                  style={{ background: 'linear-gradient(90deg, #313695 0%, #4575b4 25%, #ffffbf 50%, #fdae61 75%, #a50026 100%)' }}
                />
                <span>+40 °C</span>
              </div>
            )}

            {!result && gray && (
              <div className="mt-2 truncate text-[10px] text-gray-500" title={heightmapName}>
                {heightmapName}
              </div>
            )}

            {!result && (
              <div className="mt-3 rounded-lg border border-space-border bg-space-surface/60 p-3 text-xs leading-relaxed text-gray-500">
                {t('view.placeholder')}
              </div>
            )}
          </div>

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

          <div className="text-[10px] leading-relaxed text-gray-600">
            {result && sampleMeta && (
              <span>{t('stats.gridInfo', { name: heightmapName, width: GRID_W, height: GRID_H })}</span>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
