import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import { validPlanetValues, worldParametersKey, type PlanetValues, type WorldParameters, type WorldParameterUpdate, type WorldPlanet } from '../../api/worldParameters'
import { projectKey } from '../../projects/projectStore'

type Scope = { world: string; branch: string | null }
const inputClass = 'min-h-11 w-40 rounded-md border border-space-border bg-space-bg px-3 text-gray-100 tabular-nums focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan'

function useParameterEdit({ world, branch }: Scope, revision: string | null) {
  const client = useQueryClient()
  const [draft, setDraft] = useState<{ values: Record<string, string>; revision: string } | null>(null)
  const save = useMutation({
    mutationFn: (update: WorldParameterUpdate) => api.saveWorldParameters(world, branch, update),
    onSuccess: updated => {
      client.setQueryData(worldParametersKey(world, branch), updated)
      setDraft(null)
      void client.invalidateQueries({ queryKey: ['buildGrid', world, branch] })
      void client.invalidateQueries({ queryKey: ['world', world] })
      void client.invalidateQueries({ queryKey: projectKey(world) })
    },
  })
  const changedElsewhere = (draft !== null && draft.revision !== revision) ||
    (save.error instanceof ApiError && save.error.status === 409 && save.error.message.includes('since')) ||
    (save.error instanceof DOMException && save.error.name === 'InvalidStateError')
  const busy = save.error instanceof ApiError && save.error.status === 409 && save.error.message.includes('already active')
  return {
    draft, revision: draft?.revision ?? revision, save, changedElsewhere, busy,
    change: (field: string, value: string) => {
      if (!revision) return
      save.reset()
      setDraft(previous => ({ values: { ...previous?.values, [field]: value }, revision: previous?.revision ?? revision }))
    },
    reload: () => {
      setDraft(null)
      save.reset()
      void client.invalidateQueries({ queryKey: worldParametersKey(world, branch) })
    },
  }
}

function EditorActions({ editor, canSave }: { editor: ReturnType<typeof useParameterEdit>; canSave: boolean }) {
  const { t } = useTranslation('worlds')
  return <>
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <button type="submit" disabled={!canSave}
        className="min-h-11 rounded-md border border-neon-cyan/40 bg-neon-cyan/15 px-4 font-medium text-neon-cyan hover:bg-neon-cyan/25 focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan disabled:opacity-50">
        {t(editor.save.isPending ? 'parameters.saving' : 'parameters.save')}
      </button>
      {(editor.draft || editor.save.isError) && <button type="button" disabled={editor.save.isPending}
        className="min-h-11 rounded px-2 text-sm text-gray-200 underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan"
        onClick={editor.reload}>
        {t('parameters.reload')}
      </button>}
    </div>
    {editor.changedElsewhere ? <p role="alert" className="text-sm text-amber-200">{t('parameters.conflict')}</p> :
      editor.save.isError ? <p role="alert" className="text-sm text-amber-200">{t(editor.busy ? 'parameters.busy' : 'parameters.error')}</p> :
        editor.save.isSuccess && <p role="status" className="text-sm text-green-200">{t('parameters.saved')}</p>}
  </>
}

function InputSource({ source }: { source: string }) {
  const { t } = useTranslation('worlds')
  return <p className="text-sm text-gray-300">{t('parameters.source')}{' '}
    <code className="break-all text-xs text-gray-200">{source}</code>
  </p>
}

function GridEditor({ world, branch, settings }: Scope & { settings: WorldParameters }) {
  const { t, i18n } = useTranslation('worlds')
  const editor = useParameterEdit({ world, branch }, settings.revision)
  const value = editor.draft?.values.cells ?? String(settings.num_cells ?? '')
  const cells = Number(value)
  const valid = value.trim() !== '' && Number.isSafeInteger(cells) && cells >= settings.min_cells && cells <= settings.max_cells
  const canSave = valid && !editor.changedElsewhere && cells !== settings.num_cells && !editor.save.isPending
  const format = (count: number) => count.toLocaleString(i18n.resolvedLanguage)

  if (settings.read_only || !settings.revision) return (
    <div className="space-y-2 text-sm text-gray-300">
      {settings.num_cells !== null && <p>{t('parameters.configured', { cells: format(settings.num_cells) })}</p>}
      <p>{t(`parameters.readOnly.${settings.read_only ?? 'unavailable'}`)}</p>
    </div>
  )

  return (
    <form aria-labelledby="world-grid-label" className="max-w-2xl space-y-4" onSubmit={event => {
      event.preventDefault()
      if (canSave && editor.revision) {
        editor.save.mutate({ num_cells: cells, revision: editor.revision })
      }
    }}>
      <div className="space-y-2">
        <label id="world-grid-label" htmlFor="world-grid-cells" className="block font-medium text-gray-100">{t('parameters.grid')}</label>
        <p id="world-grid-help" className="max-w-prose text-sm leading-relaxed text-gray-300">{t('parameters.help')}</p>
        <div className="flex flex-wrap items-center gap-3">
          <input id="world-grid-cells" type="number" required step={1} min={settings.min_cells} max={settings.max_cells}
            value={value} disabled={editor.save.isPending} aria-describedby="world-grid-help world-grid-range"
            onChange={event => editor.change('cells', event.target.value)} className={inputClass} />
          <span id="world-grid-range" className="text-sm text-gray-300">
            {t('parameters.range', { min: format(settings.min_cells), max: format(settings.max_cells) })}
          </span>
        </div>
      </div>
      {settings.source && <InputSource source={settings.source} />}
      <EditorActions editor={editor} canSave={canSave} />
    </form>
  )
}

function PlanetEditor({ world, branch, settings }: Scope & { settings: WorldPlanet }) {
  const { t, i18n } = useTranslation('worlds')
  const editor = useParameterEdit({ world, branch }, settings.revision)
  const fields = ['rotation_period_days', 'albedo'] as const
  const value = (field: keyof PlanetValues) => editor.draft?.values[field] ?? String(settings[field])
  const values = { rotation_period_days: Number(value('rotation_period_days')), albedo: Number(value('albedo')) }
  const canSave = fields.every(field => value(field) !== '') && validPlanetValues(values) &&
    fields.some(field => values[field] !== settings[field]) && !editor.changedElsewhere && !editor.save.isPending
  const title = t('parameters.planet.title', { name: settings.name })

  if (settings.read_only || !settings.revision) return (
    <section className="space-y-2 border-t border-space-border pt-4 text-sm text-gray-300">
      <h3 className="font-medium text-gray-100">{title}</h3>
      <dl className="flex flex-wrap gap-x-8 gap-y-2">
        {fields.map(field => <div key={field}>
          <dt>{t(`parameters.planet.${field}.label`)}</dt>
          <dd className="text-gray-100 tabular-nums">{settings[field].toLocaleString(i18n.resolvedLanguage, { maximumSignificantDigits: 10 })}</dd>
        </div>)}
      </dl>
      {settings.read_only === 'inherited' && <p>{t('parameters.planet.inherited')}</p>}
      {settings.read_only === 'unavailable' && <p>{t('parameters.planet.unavailable')}</p>}
    </section>
  )

  return (
    <form aria-labelledby="world-planet-title" className="max-w-2xl space-y-4 border-t border-space-border pt-4"
      onSubmit={event => {
        event.preventDefault()
        if (canSave && editor.revision) editor.save.mutate({ planet: values, revision: editor.revision })
      }}>
      <h3 id="world-planet-title" className="font-medium text-gray-100">{title}</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map(field => <div key={field} className="space-y-1.5">
          <label htmlFor={`world-planet-${field}`} className="block text-sm font-medium text-gray-100">
            {t(`parameters.planet.${field}.label`)}
          </label>
          <input id={`world-planet-${field}`} type="number" required step="any" min={0}
            max={field === 'albedo' ? 1 : undefined} value={value(field)} disabled={editor.save.isPending}
            aria-describedby={`world-planet-${field}-help`} className={inputClass}
            onChange={event => editor.change(field, event.target.value)} />
          <p id={`world-planet-${field}-help`} className="text-sm leading-relaxed text-gray-300">
            {t(`parameters.planet.${field}.help`)}
          </p>
        </div>)}
      </div>
      <InputSource source={settings.source} />
      <EditorActions editor={editor} canSave={canSave} />
    </form>
  )
}

export default function WorldParametersPanel({ world, branch }: Scope) {
  const { t } = useTranslation('worlds')
  const query = useQuery({ queryKey: worldParametersKey(world, branch),
    queryFn: () => api.getWorldParameters(world, branch), retry: false })
  const editable = Boolean(query.data?.revision || query.data?.planet?.revision)
  return (
    <section aria-labelledby="world-parameters-title" className="space-y-4 rounded-xl border border-space-border bg-space-panel p-4 sm:p-6">
      <header className="space-y-1">
        <h2 id="world-parameters-title" className="text-lg font-semibold text-gray-100">{t('parameters.title')}</h2>
        <p className="max-w-prose text-sm leading-relaxed text-gray-300">
          {t(editable ? 'parameters.intro' : 'parameters.introReadOnly')}
        </p>
        <p className="text-sm text-gray-300">{t('parameters.scope', { world, branch: branch ?? t('label.baseWorld') })}</p>
        {isStaticMode() && editable && <p className="text-sm text-gray-300">{t('parameters.browser')}</p>}
      </header>
      {query.isPending ? <p role="status" className="text-sm text-gray-300">{t('status.loading')}</p> :
        query.isError ? <p role="alert" className="text-sm text-amber-200">{t('parameters.loadError')}</p> :
          <>
            <GridEditor world={world} branch={branch} settings={query.data} />
            {query.data.planet && <PlanetEditor world={world} branch={branch} settings={query.data.planet} />}
          </>}
    </section>
  )
}
