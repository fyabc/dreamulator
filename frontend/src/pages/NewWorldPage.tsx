import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { isStaticMode } from '../api/mode'
import AtlasIcon from '../components/AtlasIcon'
import CreationRaster from '../components/map/CreationRaster'
import type { TemperatureResponse } from '../playground/temperature.worker'
import { EARTH_PARAMS, type PlanetParams } from '../playground/temperatureDraft'
import { temperatureRequest } from '../playground/temperatureRequest'
import { exportHeightmapWorld, heightmapGrid, isHeightmapParams, isHeightmapWorldId, readHeightmapInput,
  savedTemperature, temperatureInputFingerprint, type HeightmapInput, type SavedTemperature } from '../projects/heightmapWorld'
import { projectsKey, worldDataPath } from '../projects/projectStore'

const field = 'w-full min-h-11 rounded border border-space-border bg-space-bg px-3 text-gray-100 focus-visible:outline focus-visible:outline-neon-cyan'
const action = 'inline-flex min-h-11 items-center justify-center gap-2 rounded border border-space-border px-4 py-2 text-gray-100 hover:border-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan disabled:opacity-50'
const importFields = ['elevMinM', 'elevMaxM', 'seaLevelM'] as const
const climateFields = [
  ['albedo', 'albedo', 0.001], ['greenhouseK', 'greenhouse', 0.5], ['tiltDeg', 'tilt', 0.1],
  ['luminosity', 'luminosity', 0.001], ['distanceAu', 'distance', 0.001],
  ['rotationDays', 'rotation', 0.01], ['yearDays', 'year', 0.1],
] as const

export default function NewWorldPage() {
  const { t } = useTranslation('worlds')
  const [selected, setSelected] = useState(false)
  const [name, setName] = useState('')
  const [fallbackId] = useState(() => `world-${crypto.randomUUID().slice(0, 8)}`)
  const [idOverride, setIdOverride] = useState<string>()
  const id = idOverride ?? (name.toLowerCase().trim().replace(/[^a-z0-9_-]+/g, '-').replace(/^[-_]+|-+$/g, '').slice(0, 48) || fallbackId)
  const [params, setParams] = useState<PlanetParams>(EARTH_PARAMS)
  const [input, setInput] = useState<HeightmapInput>()
  const [temperature, setTemperature] = useState<SavedTemperature>()
  const [stale, setStale] = useState(false)
  const [climate, setClimate] = useState(false)
  const [running, setRunning] = useState<'runtime' | 'compute' | null>(null)
  const [runError, setRunError] = useState('')
  const workerRef = useRef<Worker>()
  const query = useQueryClient()
  const navigate = useNavigate()
  const select = useMutation({ mutationFn: (file: File) => readHeightmapInput(file, file.name), onSuccess: loaded => {
    setInput(loaded)
    invalidateTemperature()
  } })
  const save = useMutation({ mutationFn: async () => {
    if (!input) throw new Error('No heightmap selected')
    const title = name.trim()
    const archive = await exportHeightmapWorld({ id, title, created: new Date().toISOString(),
      seed: crypto.getRandomValues(new Uint32Array(1))[0] >>> 1, meshCells: 2048, params, heightmap: input, temperature })
    return api.saveHeightmapWorld(id, title, archive)
  }, onSuccess: async ({ id: savedId }) => {
    await Promise.all([query.invalidateQueries({ queryKey: projectsKey }), query.invalidateQueries({ queryKey: ['worlds'] })])
    navigate(worldDataPath(savedId))
  } })
  useEffect(() => () => workerRef.current?.terminate(), [])

  const busy = select.isPending || save.isPending || running !== null
  const paramsValid = isHeightmapParams(params)
  const canSave = !!(input && name.trim() && paramsValid && isHeightmapWorldId(id)) && !busy

  function invalidateTemperature() {
    if (temperature) setStale(true)
    setTemperature(undefined)
    setRunError('')
  }

  function numberField(key: typeof importFields[number] | typeof climateFields[number][0], label: string, step: number | 'any') {
    return <label key={key} className="flex min-w-0 flex-col gap-1 text-sm text-gray-200">{label}
      <input className={field} type="number" step={step} value={Number.isFinite(params[key]) ? params[key] : ''}
        onChange={event => {
          const value = event.currentTarget.valueAsNumber
          setParams(previous => ({ ...previous, [key]: value }))
          invalidateTemperature()
        }} />
    </label>
  }

  async function run() {
    if (!input || !paramsValid || busy) return
    setRunError('')
    setRunning(workerRef.current ? 'compute' : 'runtime')
    const fail = (detail: string) => {
      workerRef.current?.terminate()
      workerRef.current = undefined
      setRunning(null)
      setRunError(detail || t('creation.runError'))
    }
    try {
      const fingerprint = await temperatureInputFingerprint(input, params)
      const worker = workerRef.current ?? new Worker(new URL('../playground/temperature.worker.ts', import.meta.url), { type: 'module' })
      workerRef.current = worker
      worker.onerror = event => fail(event.message)
      worker.onmessage = ({ data }: MessageEvent<TemperatureResponse>) => {
        if (data.type === 'runtime-ready') setRunning('compute')
        else if (data.type === 'result') {
          setTemperature(savedTemperature(data.result, fingerprint, data.version))
          setStale(false)
          setRunning(null)
        } else fail(data.detail)
      }
      const elevation = heightmapGrid(input, params).values
      worker.postMessage(temperatureRequest(elevation, params), [elevation.buffer])
    } catch (error) { fail(String(error)) }
  }

  return <section aria-labelledby="new-world-heading" className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-8">
    <header className="space-y-2">
      <Link to="/worlds" className="inline-flex min-h-10 items-center gap-2 text-sm text-gray-300 hover:text-neon-cyan">
        <AtlasIcon name="back" />{t('title.list')}
      </Link>
      <h1 id="new-world-heading" className="text-3xl font-semibold text-gray-100">{t('action.newWorld')}</h1>
      <p className="max-w-2xl text-gray-400">{t(selected ? 'creation.steps' : 'creation.choose')}</p>
    </header>
    {!selected ? <div className="max-w-2xl divide-y divide-space-border border-y border-space-border">
      <button type="button" onClick={() => setSelected(true)} className="flex min-h-24 w-full items-center justify-between gap-4 py-3 text-start hover:text-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan">
        <span><span className="block text-lg font-medium">{t('creation.hasHeightmap')}</span>
          <span className="mt-1 block text-sm text-gray-400">{t('creation.hasHeightmapHelp')}</span></span><AtlasIcon name="arrow" />
      </button>
      <Link to="/worlds?create=1" className="flex min-h-24 items-center justify-between gap-4 py-3 hover:text-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan">
        <span><span className="block text-lg font-medium">{t('creation.fromScratch')}</span>
          <span className="mt-1 block text-sm text-gray-400">{t('creation.fromScratchHelp')}</span></span><AtlasIcon name="arrow" />
      </Link>
    </div> : <form noValidate onSubmit={event => { event.preventDefault(); if (canSave) save.mutate() }} className="space-y-6">
      <fieldset disabled={busy} className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,22rem)_1fr]">
        <div className="min-w-0 space-y-4">
          <h2 className="text-lg font-semibold">{t('creation.hasHeightmap')}</h2>
          <label className="flex flex-col items-start gap-2 text-sm text-gray-200">{t('creation.selectFile')}
            <span className={`${action} cursor-pointer focus-within:outline focus-within:outline-neon-cyan aria-disabled:cursor-default aria-disabled:opacity-50`} aria-disabled={busy}>
              {t(input ? 'creation.replaceFile' : 'creation.chooseFile')}
              <input type="file" aria-label={t('creation.selectFile')} accept="image/png,.png" className="sr-only"
              onChange={event => {
                const file = event.currentTarget.files?.[0]
                event.currentTarget.value = ''
                if (file) select.mutate(file)
              }} />
            </span>
          </label>
          <p className="text-sm text-gray-400">{t('creation.fileHelp')}</p>
          {select.isPending && <p role="status" className="text-sm">{t('creation.reading')}</p>}
          {select.isError && <p role="alert" className="text-sm text-red-300">{t('creation.fileError')} {select.error.message}</p>}
          {input && <p className="break-all text-sm text-neon-cyan">{input.filename}</p>}
          {importFields.map(key => numberField(key, t(`creation.${key}`), 'any'))}
        </div>
        {input && paramsValid ? <CreationRaster key={temperature?.fingerprint ?? 'terrain'} input={input} params={params} temperature={temperature} />
          : <div className="grid min-h-32 place-items-center rounded border border-space-border bg-space-panel p-5 text-center text-gray-400">{t('creation.previewEmpty')}</div>}
      </fieldset>
      <section className="space-y-3 border-t border-space-border pt-5">
        {!climate ? <button type="button" onClick={() => setClimate(true)} className={action} disabled={!input || busy}>
          <AtlasIcon name="flask" />{t('creation.tryClimate')}</button> : <>
          <h2 className="text-lg font-semibold">{t('playground:params.title')}</h2>
          <p className="max-w-2xl text-sm text-gray-400">{t('playground:note')}</p>
          <fieldset disabled={busy} className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {climateFields.map(([key, label, step]) => numberField(key, t(`playground:params.${label}`), step))}
            <label className="flex min-h-11 items-center gap-2 text-sm text-gray-200">
              <input type="checkbox" checked={params.variableLapse} onChange={event => {
                setParams(previous => ({ ...previous, variableLapse: event.target.checked })); invalidateTemperature()
              }} />{t('playground:params.variableLapse')}
            </label>
          </fieldset>
          <p className="text-sm text-gray-400">{t('creation.experimentSettings')}</p>
          <button type="button" className={action} disabled={!input || !paramsValid || busy} onClick={() => void run()}>{t('playground:action.run')}</button>
          {running && <p role="status" className="text-sm text-gray-300">{t(running === 'runtime' ? 'creation.runtime' : 'creation.computing')}</p>}
          {runError && <p role="alert" className="text-sm text-red-300">{t('creation.runError')} {runError}</p>}
          {(temperature || stale) && <p role="status" className="text-sm text-gray-300">{t(temperature ? 'creation.resultReady' : 'creation.stale')}</p>}
        </>}
      </section>
      <fieldset disabled={busy} className="min-w-0 space-y-4 border-t border-space-border pt-5">
        <label className="flex max-w-sm flex-col gap-1 text-sm text-gray-200">{t('label.worldName')}
          <input className={field} type="text" value={name} maxLength={120} onChange={event => setName(event.currentTarget.value)} />
        </label>
        <details className="max-w-sm text-sm text-gray-400">
          <summary className="min-h-10 cursor-pointer content-center">{t('creation.id')}</summary>
          <input className={field} aria-label={t('creation.id')} value={id} maxLength={48} onChange={event => setIdOverride(event.currentTarget.value)} />
          <p className="mt-1">{t('creation.idHelp')}</p>
        </details>
        {!paramsValid && <p role="alert" className="text-sm text-red-300">{t('playground:error.params')}</p>}
        {!isHeightmapWorldId(id) && <p role="alert" className="text-sm text-red-300">{t('creation.idError')}</p>}
        <button type="submit" disabled={!canSave} className={`${action} border-neon-cyan/50 bg-neon-cyan/10 text-neon-cyan`}>
          {t(save.isPending ? 'worldData.saving' : temperature ? 'creation.saveWithResult' : 'creation.save')}
        </button>
        <p className="text-sm text-gray-400">{t(isStaticMode() ? 'creation.browserSave' : 'creation.localSave')}</p>
        {save.isError && <p role="alert" className="break-words text-sm text-red-300">{t('creation.saveError')} {save.error.message}</p>}
      </fieldset>
    </form>}
  </section>
}
