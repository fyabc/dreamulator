import { useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '../api/client'
import { isStaticMode } from '../api/mode'
import AtlasIcon from '../components/AtlasIcon'
import ElevationAdvice from '../components/import/ElevationAdvice'
import CreationRaster from '../components/map/CreationRaster'
import { EARTH_PARAMS } from '../playground/temperatureDraft'
import { defaultHeightmapCells, exportHeightmapWorld, heightmapDiagnostics, isHeightmapMapping, isHeightmapParams,
  rangeMapping, readHeightmapInput, thresholdSeaLevel, type HeightmapInput,
  type HeightmapMapping } from '../projects/heightmapWorld'
import { isCreationWorldId } from '../projects/creationSnapshot'
import { isStarterSeed, starterTemplates, type StarterTemplate } from '../projects/starterWorld'
import { projectsKey, worldOverviewPath } from '../projects/projectStore'
import { tutorialMilestone } from '../tutorial/tutorialProgress'

const field = 'w-full min-h-10 rounded border border-space-border bg-space-bg px-3 text-gray-100 focus-visible:outline focus-visible:outline-neon-cyan'
const action = 'inline-flex min-h-11 items-center justify-center gap-2 rounded border border-space-border px-4 py-2 text-gray-100 hover:border-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan disabled:opacity-50'
const saveAction = `${action} border-neon-cyan/50 bg-neon-cyan/10 text-neon-cyan`
const randomSeed = () => crypto.getRandomValues(new Uint32Array(1))[0] >>> 1
const importFields = ['elevMinM', 'elevMaxM', 'seaLevelM'] as const

export default function NewWorldPage() {
  const { t } = useTranslation('worlds')
  const [search] = useSearchParams()
  const start = search.get('start')
  const selected = start === 'heightmap'
  const starter = start === 'template'
  const [name, setName] = useState('')
  const [fallbackId] = useState(() => `world-${crypto.randomUUID().slice(0, 8)}`)
  const [idOverride, setIdOverride] = useState<string>()
  const id = idOverride ?? (name.toLowerCase().trim().replace(/[^a-z0-9_-]+/g, '-').replace(/^[-_]+|-+$/g, '').slice(0, 48) || fallbackId)
  const [template, setTemplate] = useState<StarterTemplate>('minimal')
  const [seed, setSeed] = useState(randomSeed)
  const [params, setParams] = useState(EARTH_PARAMS)
  const [input, setInput] = useState<HeightmapInput>()
  const [mappingMode, setMappingMode] = useState<'range' | 'threshold'>('range')
  const [threshold, setThreshold] = useState<Extract<HeightmapMapping, { mode: 'threshold' }>>(() => ({
    mode: 'threshold', sea_level: 0, max_m: EARTH_PARAMS.elevMaxM, seafloor_m: -3800, curve: 'linear', gamma: 1 }))
  const [showAdvanced, setShowAdvanced] = useState(false)
  const query = useQueryClient()
  const navigate = useNavigate()
  const select = useMutation({ mutationFn: async (file: File | 'earth') => {
    if (file !== 'earth') return { loaded: await readHeightmapInput(file, file.name) }
    const [elevation, meta] = await Promise.all([
      api.getElevationBlob('earth', 'planet_earth'), api.getMapMeta('earth', 'planet_earth'),
    ])
    const loaded = await readHeightmapInput(elevation, 'earth-etopo1.png')
    if (meta.projection !== 'equirectangular' || loaded.raster.width !== meta.width || loaded.raster.height !== meta.height ||
      ![meta.sea_level_m, meta.elevation_min_m, meta.elevation_max_m].every(Number.isFinite) ||
      !(meta.elevation_min_m < meta.elevation_max_m)) throw new Error('Invalid sample heightmap metadata')
    return { loaded, mapping: { elevMinM: meta.elevation_min_m, elevMaxM: meta.elevation_max_m, seaLevelM: meta.sea_level_m } }
  }, onSuccess: ({ loaded, mapping }) => {
    setInput(loaded)
    setThreshold(previous => ({ ...previous, sea_level: thresholdSeaLevel(loaded) }))
    if (mapping) setParams(previous => ({ ...previous, ...mapping }))
  } })
  const save = useMutation({ mutationFn: async () => {
    const title = name.trim()
    if (starter) return api.saveStarterWorld({ id, title, template, seed })
    if (!input) throw new Error('No heightmap selected')
    const archive = await exportHeightmapWorld({ id, title, created: new Date().toISOString(),
      seed: randomSeed(), meshCells: defaultHeightmapCells, params, mapping, heightmap: input })
    return api.saveHeightmapWorld(id, title, archive)
  }, onSuccess: async ({ id: savedId }) => {
    await Promise.all([query.invalidateQueries({ queryKey: projectsKey }), query.invalidateQueries({ queryKey: ['worlds'] })])
    if (selected) tutorialMilestone({ type: 'imported', world: savedId })
    navigate(worldOverviewPath(savedId))
  } })
  const busy = select.isPending || save.isPending
  const paramsValid = isHeightmapParams(params)
  const rangeMap = useMemo(() => rangeMapping(params), [params.elevMinM, params.elevMaxM, params.seaLevelM])
  const mapping: HeightmapMapping = mappingMode === 'range' ? rangeMap : threshold
  const mappingValid = isHeightmapMapping(mapping)
  const mappingAdvice = useMemo(() => (input && mappingValid ? heightmapDiagnostics(input, mapping) : []),
    [input, mapping, mappingValid])
  const canSave = !!(name.trim() && isCreationWorldId(id) &&
    (starter ? isStarterSeed(seed) : input && paramsValid && mappingValid)) && !busy
  const thresholdLevels = input ? (input.raster.depth === 8 ? 255 : 65535) : 255
  const changeMode = (next: 'range' | 'threshold') => {
    if (next === 'threshold') setThreshold(previous => ({ ...previous, max_m: params.elevMaxM }))
    setMappingMode(next)
  }
  const conflict = (save.error instanceof ApiError && save.error.status === 409) ||
    (save.error instanceof DOMException && save.error.name === 'ConstraintError')

  const identityFields = <>
    <label className="flex max-w-sm flex-col gap-1 text-sm text-gray-200">{t('label.worldName')}
      <input className={field} type="text" required value={name} maxLength={120} onChange={event => setName(event.currentTarget.value)} />
    </label>
    <details className="max-w-sm text-sm text-gray-400">
      <summary className="min-h-10 cursor-pointer content-center">{t('creation.id')}</summary>
      <input className={field} aria-label={t('creation.id')} value={id} maxLength={48} onChange={event => setIdOverride(event.currentTarget.value)} />
      <p className="mt-1">{t('creation.idHelp')}</p>
    </details>
    {!isCreationWorldId(id) && <p role="alert" className="text-sm text-red-300">{t('creation.idError')}</p>}
  </>

  const saveFooter = <>
    <p className="max-w-prose text-sm text-gray-400">
      {t(isStaticMode() ? starter ? 'creation.starter.browserSave' : 'creation.browserSave' : 'creation.localSave')}
    </p>
    <button type="submit" disabled={!canSave} className={saveAction}>
      {t(save.isPending ? 'worldData.saving' : 'creation.save')}
    </button>
    {save.isError && <p role="alert" className="break-words text-sm text-red-300">
      {conflict ? t('creation.idConflict') : `${t(starter ? 'creation.starter.saveError' : 'creation.saveError')} ${save.error.message}`}
    </p>}
  </>

  return <section aria-labelledby="new-world-heading" className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-8">
    <header className="space-y-2">
      {!busy && <Link to={selected || starter ? '/new-world' : '/worlds'} onClick={() => save.reset()}
        className="inline-flex min-h-10 items-center gap-2 text-sm text-gray-300 hover:text-neon-cyan">
        <AtlasIcon name="back" />{t(selected || starter ? 'creation.changeStart' : 'title.list')}
      </Link>}
      <h1 id="new-world-heading" className="text-3xl font-semibold text-gray-100">{t('action.newWorld')}</h1>
      <p className="max-w-2xl text-gray-400">{t(starter ? 'creation.starter.steps' : selected ? 'creation.steps' : 'creation.choose')}</p>
    </header>
    {!selected && !starter ? <div className="max-w-2xl divide-y divide-space-border border-y border-space-border">
      <button type="button" onClick={() => navigate('?start=heightmap')} className="flex min-h-24 w-full items-center justify-between gap-4 py-3 text-start hover:text-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan">
        <span><span className="block text-lg font-medium">{t('creation.hasHeightmap')}</span>
          <span className="mt-1 block text-sm text-gray-400">{t('creation.hasHeightmapHelp')}</span></span><AtlasIcon name="arrow" />
      </button>
      <Link to="?start=template" className="flex min-h-24 items-center justify-between gap-4 py-3 hover:text-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan">
        <span><span className="block text-lg font-medium">{t('creation.fromScratch')}</span>
          <span className="mt-1 block text-sm text-gray-400">{t('creation.fromScratchHelp')}</span></span><AtlasIcon name="arrow" />
      </Link>
    </div> : starter ? <form key="starter" noValidate onSubmit={event => { event.preventDefault(); if (canSave) save.mutate() }} className="max-w-2xl space-y-5">
      <fieldset disabled={busy} className="min-w-0 space-y-3">
        <legend className="text-lg font-semibold">{t('creation.starter.chooseTemplate')}</legend>
        <div className="divide-y divide-space-border border-y border-space-border">
          {starterTemplates.map(option => <label key={option}
            className="flex min-h-16 cursor-pointer items-start gap-3 px-2 py-3 has-[:checked]:bg-space-panel">
            <input type="radio" name="template" className="mt-1 accent-neon-cyan" value={option} checked={template === option}
              onChange={() => setTemplate(option)} />
            <span><span className="block font-medium text-gray-100">{t(`creation.starter.${option}`)}</span>
              <span className="block text-sm text-gray-400">{t(`creation.starter.${option}Help`)}</span></span>
          </label>)}
        </div>
      </fieldset>
      <fieldset disabled={busy} className="min-w-0 space-y-3">
        <legend className="mb-3 text-lg font-semibold">{t('creation.starter.settings')}</legend>
        {identityFields}
        <div className="max-w-sm space-y-1 text-sm">
          <label className="flex flex-col gap-1 text-gray-200">{t('creation.starter.seed')}
            <input className={field} type="number" min={0} max={2147483647} step={1} required aria-describedby="starter-seed-help"
              value={Number.isFinite(seed) ? seed : ''} onChange={event => setSeed(event.currentTarget.valueAsNumber)} />
          </label>
          <p id="starter-seed-help" className="text-gray-400">{t('creation.starter.seedHelp')}</p>
        </div>
        {!isStarterSeed(seed) && <p role="alert" className="text-sm text-red-300">{t('creation.starter.seedError')}</p>}
        {saveFooter}
      </fieldset>
    </form> : <form key="heightmap" noValidate onSubmit={event => { event.preventDefault(); if (canSave) save.mutate() }} className="space-y-6">
      <fieldset disabled={busy} className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,22rem)_1fr]">
        <div className="min-w-0 space-y-4">
          <h2 className="text-lg font-semibold">{t('creation.hasHeightmap')}</h2>
          <div data-tutorial-anchor="upload" role="group" aria-labelledby="heightmap-source-label" className="space-y-2">
            <p id="heightmap-source-label" className="text-sm text-gray-200">{t('creation.selectFile')}</p>
            <div className="flex flex-wrap gap-2">
              <label className={`${action} cursor-pointer text-sm focus-within:outline focus-within:outline-neon-cyan aria-disabled:cursor-default aria-disabled:opacity-50`} aria-disabled={busy}>
                {t(input ? 'creation.replaceFile' : 'creation.chooseFile')}
                <input type="file" aria-label={t('creation.selectFile')} accept="image/png,image/jpeg,.png,.jpg,.jpeg" className="sr-only"
                onChange={event => {
                  const file = event.currentTarget.files?.[0]
                  event.currentTarget.value = ''
                  if (file) select.mutate(file)
                }} />
              </label>
              <button type="button" onClick={() => select.mutate('earth')} className={`${action} text-sm`}>
                {t('creation.earthSample')}
              </button>
            </div>
          </div>
          <p className="text-sm text-gray-400">{t('creation.fileHelp')}</p>
          {select.isPending && <p role="status" className="text-sm">{t('creation.reading')}</p>}
          {select.isError && <p role="alert" className="text-sm text-red-300">{select.variables === 'earth'
            ? t('creation.earthSampleError') : `${t('creation.fileError')} ${select.error.message}`}</p>}
          {input && <p className="break-all text-sm text-neon-cyan">{input.filename}</p>}
          {input?.converted && <p role="status" className="text-sm text-amber-300">{t('creation.convertedFromJpeg')}</p>}
          <fieldset className="space-y-1 text-sm text-gray-200">
            <legend className="mb-1">{t('creation.mapping')}</legend>
            <label className="flex items-start gap-2">
              <input type="radio" name="mapping-mode" className="mt-1 accent-neon-cyan" checked={mappingMode === 'range'}
                onChange={() => changeMode('range')} />
              <span><span className="block">{t('creation.mappingRange')}</span>
                <span className="block text-xs text-gray-500">{t('creation.mappingRangeHelp')}</span></span>
            </label>
            <label className="flex items-start gap-2">
              <input type="radio" name="mapping-mode" className="mt-1 accent-neon-cyan" checked={mappingMode === 'threshold'}
                onChange={() => changeMode('threshold')} />
              <span><span className="block">{t('creation.mappingThreshold')}</span>
                <span className="block text-xs text-gray-500">{t('creation.mappingThresholdHelp')}</span></span>
            </label>
          </fieldset>
          {input && mappingValid && <ElevationAdvice diagnostics={mappingAdvice} />}
          {mappingMode === 'range' ? importFields.map(key => <label key={key} className="flex min-w-0 flex-col gap-1 text-sm text-gray-200">{t(`creation.${key}`)}
            <input className={field} type="number" step="any" value={Number.isFinite(params[key]) ? params[key] : ''}
              onChange={event => {
                const value = event.currentTarget.valueAsNumber
                setParams(previous => ({ ...previous, [key]: value }))
              }} />
          </label>) : <>
            <MappingField label={t('creation.seaThreshold')} note={t('creation.seaThresholdGrey', { levels: thresholdLevels })}
              help={t('creation.seaThresholdHelp')} step={1} min={0} max={thresholdLevels - 1}
              value={Math.round(threshold.sea_level * thresholdLevels)}
              onChange={grey => setThreshold(previous => ({ ...previous, sea_level: Number.isFinite(grey)
                ? Math.min(thresholdLevels - 1, Math.max(0, Math.round(grey))) / thresholdLevels : Number.NaN }))} />
            <MappingField label={t('creation.elevMaxM')} help={t('creation.thresholdMaxHelp')} value={threshold.max_m}
              onChange={value => setThreshold(previous => ({ ...previous, max_m: value }))} />
            <MappingField label={t('creation.seafloorM')} help={t('creation.seafloorHelp')} value={threshold.seafloor_m}
              onChange={value => setThreshold(previous => ({ ...previous, seafloor_m: value }))} />
            <button type="button" aria-expanded={showAdvanced}
              className="inline-flex min-h-10 items-center gap-2 self-start rounded border border-space-border bg-space-panel px-3 py-1.5 text-sm text-gray-200 hover:border-neon-cyan hover:text-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan"
              onClick={() => setShowAdvanced(shown => !shown)}>
              {t('creation.advancedMapping')}
              <span aria-hidden className="text-xs">{showAdvanced ? '▴' : '▾'}</span>
            </button>
            {showAdvanced && <div className="space-y-2 border-l border-space-border pl-3">
              <label className="block text-sm text-gray-300" title={t('creation.curveHelp')}>{t('creation.curve')}
                <select className="ml-2 rounded border border-space-border bg-space-surface px-2 py-0.5 text-sm" value={threshold.curve}
                  title={t('creation.curveHelp')}
                  onChange={event => {
                    // Read the value before the updater runs: React may invoke it after
                    // the synthetic event has been reset (currentTarget becomes null).
                    const curve = event.currentTarget.value === 'gamma' ? 'gamma' : 'linear'
                    setThreshold(previous => ({ ...previous, curve }))
                  }}>
                  <option value="linear">{t('creation.curveLinear')}</option>
                  <option value="gamma">{t('creation.curveGamma')}</option>
                </select>
              </label>
              {threshold.curve === 'gamma' && (
                <MappingField label={t('creation.gamma')} help={t('creation.gammaHelp')} value={threshold.gamma}
                  onChange={value => setThreshold(previous => ({ ...previous, gamma: value }))} />
              )}
            </div>}
          </>}
          {!mappingValid && <p role="alert" className="text-sm text-red-300">{t('creation.mappingError')}</p>}
        </div>
        {input && mappingValid ? <CreationRaster input={input} mapping={mapping} />
          : <div className="grid min-h-32 place-items-center rounded border border-space-border bg-space-panel p-5 text-center text-gray-400">{t('creation.previewEmpty')}</div>}
      </fieldset>
      <fieldset disabled={busy} className="min-w-0 border-t border-space-border pt-5">
        <div data-tutorial-anchor={input ? 'configure' : undefined} className="max-w-prose space-y-4">
          {identityFields}
          {!paramsValid && <p role="alert" className="text-sm text-red-300">{t('playground:error.params')}</p>}
          {saveFooter}
        </div>
      </fieldset>
    </form>}
  </section>
}

/** A numeric threshold-mapping field with the same look as the range fields. */
function MappingField({ label, value, help, note, step, min, max, onChange }: {
  label: string; value: number; help?: string; note?: string; step?: number; min?: number; max?: number
  onChange: (value: number) => void
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1 text-sm text-gray-200">{label}
      <input className={field} type="number" step={step ?? 'any'} min={min} max={max}
        value={Number.isFinite(value) ? value : ''}
        onChange={event => onChange(event.currentTarget.valueAsNumber)} />
      {note && <span className="text-xs text-gray-500">{note}</span>}
      {help && <span className="text-xs text-gray-500">{help}</span>}
    </label>
  )
}
