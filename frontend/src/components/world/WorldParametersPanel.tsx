import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import { validPlanetValues, worldParametersKey, type PlanetValues, type WorldParameters, type WorldParameterUpdate, type WorldPlanet } from '../../api/worldParameters'
import { projectKey } from '../../projects/projectStore'
import AtlasIcon from '../AtlasIcon'

type Scope = { world: string; branch: string | null }
const inputClass = 'min-h-10 w-full rounded-md border border-space-border bg-space-bg px-2.5 text-gray-100 tabular-nums aria-[invalid=true]:border-amber-200/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan sm:min-h-9'
const rowsClass = 'divide-y divide-space-border border-y border-space-border'

function groupStatus(readOnly: WorldParameters['read_only']) {
  if (readOnly === 'reference' || readOnly === 'published') return undefined
  return readOnly === 'inherited' ? 'parameters.inheritedLabel' : 'parameters.readOnlyLabel'
}

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

function EditorActions({ editor, canSave, details }: { editor: ReturnType<typeof useParameterEdit>; canSave: boolean; details: ReactNode }) {
  const { t } = useTranslation('worlds')
  return <>
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <button type="submit" disabled={!canSave}
        className="min-h-10 rounded-md border border-neon-cyan/40 bg-neon-cyan/15 px-3 text-sm font-medium text-neon-cyan hover:bg-neon-cyan/25 focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan disabled:opacity-50">
        {t(editor.save.isPending ? 'parameters.saving' : 'parameters.save')}
      </button>
      {(editor.draft || editor.save.isError) && <button type="button" disabled={editor.save.isPending}
        className="min-h-10 rounded px-1 text-sm text-gray-200 underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan"
        onClick={editor.reload}>
        {t('parameters.reload')}
      </button>}
      {details}
    </div>
    {editor.changedElsewhere ? <p role="alert" className="text-sm text-amber-200">{t('parameters.conflict')}</p> :
      editor.save.isError ? <p role="alert" className="text-sm text-amber-200">{t(editor.busy ? 'parameters.busy' : 'parameters.error')}</p> :
        editor.save.isSuccess && <p role="status" className="text-sm text-green-200">{t('parameters.saved')}</p>}
  </>
}

function ParameterDetails({ group, source }: { group: string; source: string | null }) {
  const { t } = useTranslation('worlds')
  if (!source) return null
  return <details className="min-w-0 max-w-full text-sm open:basis-full">
    <summary aria-label={t('parameters.detailsFor', { group })}
      className="w-fit cursor-pointer rounded py-2 text-gray-300 marker:text-gray-400 hover:text-neon-cyan focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan">
      {t('parameters.details')}
    </summary>
    <p className="max-w-prose pb-1 leading-relaxed text-gray-300">
      {t('parameters.source')}{' '}<code className="break-all text-xs text-gray-200">{source}</code>
    </p>
  </details>
}

function ParameterHeading({ id, title, context, status }: { id: string; title: string; context?: string; status?: string }) {
  return <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
    <h3 id={id} className="font-semibold text-gray-100">{title}</h3>
    {context && <span className="min-w-0 break-words text-sm text-gray-300">{context}</span>}
    {status && <span className="text-sm text-gray-400">{status}</span>}
  </div>
}

function ParameterLabel({ id, label, help, restriction, editable }: {
  id: string; label: string; help: string; restriction?: string; editable: boolean
}) {
  const { t } = useTranslation('worlds')
  const [open, setOpen] = useState(false)
  return <div className="relative col-span-2 flex items-center gap-1 sm:col-span-1"
    onPointerLeave={event => { if (event.pointerType === 'mouse') setOpen(false) }}>
    {editable ? <label htmlFor={id} className="font-medium text-gray-100">{label}</label>
      : <span className="font-medium text-gray-100">{label}</span>}
    <button type="button" aria-label={t('parameters.helpFor', { label })} aria-describedby={`${id}-help`}
      className="inline-grid size-6 shrink-0 place-items-center rounded text-gray-400 hover:text-neon-cyan focus-visible:text-neon-cyan focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan"
      onPointerEnter={event => { if (event.pointerType === 'mouse') setOpen(true) }}
      onFocus={event => { if (event.currentTarget.matches(':focus-visible')) setOpen(true) }}
      onBlur={() => setOpen(false)} onClick={() => setOpen(true)}
      onKeyDown={event => { if (event.key === 'Escape') setOpen(false) }}>
      <AtlasIcon name="help" className="size-4" />
    </button>
    <div id={`${id}-help`} role="tooltip" className={`${open ? 'visible' : 'invisible'} absolute left-0 top-full z-20 w-72 max-w-[calc(100vw-4.5rem)] space-y-1 rounded-md border border-space-border bg-space-surface px-3 py-2 text-sm leading-relaxed text-gray-200`}>
      <p>{help}</p>
      {restriction && <p>{restriction}</p>}
    </div>
  </div>
}

function ParameterRow({ id, label, help, restriction, value, hint, children }: {
  id: string; label: string; help: string; restriction?: string; value?: string; hint?: string; children?: ReactNode
}) {
  return <div className="grid min-w-0 grid-cols-[minmax(0,7rem)_minmax(0,1fr)] items-center gap-x-3 gap-y-1 py-2 text-sm sm:grid-cols-[minmax(0,1.2fr)_7rem_minmax(0,1fr)]">
    <ParameterLabel id={id} label={label} help={help} restriction={restriction} editable={Boolean(children)} />
    {children ?? <span className="break-words tabular-nums text-gray-100">{value}</span>}
    {hint && <span id={`${id}-hint`} className="text-gray-300">{hint}</span>}
  </div>
}

function GridEditor({ world, branch, settings }: Scope & { settings: WorldParameters }) {
  const { t, i18n } = useTranslation('worlds')
  const editor = useParameterEdit({ world, branch }, settings.revision)
  const value = editor.draft?.values.cells ?? String(settings.num_cells ?? '')
  const cells = Number(value)
  const valid = value.trim() !== '' && Number.isSafeInteger(cells) && cells >= settings.min_cells && cells <= settings.max_cells
  const canSave = valid && !editor.changedElsewhere && cells !== settings.num_cells && !editor.save.isPending
  const format = (count: number) => count.toLocaleString(i18n.resolvedLanguage)
  const title = t('parameters.groups.terrain')
  const id = 'world-grid-cells'
  const label = t('parameters.grid')
  const status = groupStatus(settings.read_only)
  const help = t('parameters.help')
  const restriction = status && (settings.read_only || !settings.revision)
    ? t(`parameters.readOnly.${settings.read_only ?? 'unavailable'}`) : undefined
  const details = <ParameterDetails group={title} source={settings.source} />

  if (settings.read_only || !settings.revision) return (
    <section aria-labelledby="world-grid-title" className="space-y-2">
      <ParameterHeading id="world-grid-title" title={title} status={status && t(status)} />
      {settings.num_cells === null
        ? <p className="text-sm text-gray-300">{restriction ?? t('parameters.noGridValue')}</p>
        : <div className={rowsClass}>
          <ParameterRow id={id} label={label} help={help} restriction={restriction}
            value={format(settings.num_cells)} hint={t('parameters.cellsUnit')} />
        </div>}
      {details}
    </section>
  )

  return (
    <form aria-labelledby="world-grid-title" className="space-y-2" onSubmit={event => {
      event.preventDefault()
      if (canSave && editor.revision) {
        editor.save.mutate({ num_cells: cells, revision: editor.revision })
      }
    }}>
      <ParameterHeading id="world-grid-title" title={title} />
      <div className={rowsClass}>
        <ParameterRow id={id} label={label} help={help} hint={t('parameters.range', { min: format(settings.min_cells), max: format(settings.max_cells) })}>
          <input id={id} type="number" required step={1} min={settings.min_cells} max={settings.max_cells}
            value={value} disabled={editor.save.isPending} aria-describedby={`${id}-hint ${id}-help`}
            aria-invalid={editor.draft !== null && !valid}
            onChange={event => editor.change('cells', event.target.value)} className={inputClass} />
        </ParameterRow>
      </div>
      <EditorActions editor={editor} canSave={canSave} details={details} />
    </form>
  )
}

function PlanetEditor({ world, branch, settings }: Scope & { settings: WorldPlanet }) {
  const { t, i18n } = useTranslation('worlds')
  const editor = useParameterEdit({ world, branch }, settings.revision)
  const fields = ['rotation_period_days', 'albedo'] as const
  const value = (field: keyof PlanetValues) => editor.draft?.values[field] ?? String(settings[field])
  const values = { rotation_period_days: Number(value('rotation_period_days')), albedo: Number(value('albedo')) }
  const invalid = (field: keyof PlanetValues) => value(field) === '' || !validPlanetValues({ ...settings, [field]: values[field] })
  const canSave = fields.every(field => value(field) !== '') && validPlanetValues(values) &&
    fields.some(field => values[field] !== settings[field]) && !editor.changedElsewhere && !editor.save.isPending
  const title = t('parameters.groups.planet')
  const context = t('parameters.planet.title', { name: settings.name })
  const status = groupStatus(settings.read_only)
  const restriction = status && (settings.read_only || !settings.revision)
    ? t(settings.read_only === 'inherited' ? 'parameters.planet.inherited' : 'parameters.planet.unavailable') : undefined
  const details = <ParameterDetails group={title} source={settings.source} />

  if (settings.read_only || !settings.revision) return (
    <section aria-labelledby="world-planet-title" className="space-y-2">
      <ParameterHeading id="world-planet-title" title={title} context={context} status={status && t(status)} />
      <div className={rowsClass}>
        {fields.map(field => <ParameterRow key={field} id={`world-planet-${field}`} label={t(`parameters.planet.${field}.label`)}
          help={t(`parameters.planet.${field}.help`)} restriction={restriction}
          value={settings[field].toLocaleString(i18n.resolvedLanguage, { maximumSignificantDigits: 10 })}
          hint={field === 'rotation_period_days' ? t('parameters.planet.rotation_period_days.unit') : undefined} />)}
      </div>
      {details}
    </section>
  )

  return (
    <form aria-labelledby="world-planet-title" className="space-y-2"
      onSubmit={event => {
        event.preventDefault()
        if (canSave && editor.revision) editor.save.mutate({ planet: values, revision: editor.revision })
      }}>
      <ParameterHeading id="world-planet-title" title={title} context={context} />
      <div className={rowsClass}>
        {fields.map(field => <ParameterRow key={field} id={`world-planet-${field}`} label={t(`parameters.planet.${field}.label`)}
          help={t(`parameters.planet.${field}.help`)} hint={t(`parameters.planet.${field}.constraint`)}>
          <input id={`world-planet-${field}`} type="number" required step="any" min={0}
            max={field === 'albedo' ? 1 : undefined} value={value(field)} disabled={editor.save.isPending}
            aria-describedby={`world-planet-${field}-hint world-planet-${field}-help`} className={inputClass}
            aria-invalid={editor.draft?.values[field] !== undefined && invalid(field)}
            onChange={event => editor.change(field, event.target.value)} />
        </ParameterRow>)}
      </div>
      <EditorActions editor={editor} canSave={canSave} details={details} />
    </form>
  )
}

export default function WorldParametersPanel({ world, branch }: Scope) {
  const { t } = useTranslation('worlds')
  const query = useQuery({ queryKey: worldParametersKey(world, branch),
    queryFn: () => api.getWorldParameters(world, branch), retry: false })
  const editable = Boolean(query.data?.revision || query.data?.planet?.revision)
  const readOnly = query.data?.read_only
  return (
    <section aria-labelledby="world-parameters-title" className="space-y-5 rounded-xl border border-space-border bg-space-panel p-4 sm:p-6">
      <header className="space-y-1">
        <h2 id="world-parameters-title" className="text-lg font-semibold text-gray-100">{t('parameters.title')}</h2>
        {query.data && <p className="max-w-prose text-sm leading-relaxed text-gray-300">
          {t(editable ? (isStaticMode() ? 'parameters.browser' : 'parameters.intro') :
            readOnly === 'reference' || readOnly === 'published' ? `parameters.readOnly.${readOnly}` : 'parameters.introReadOnly')}
        </p>}
      </header>
      {query.isPending ? <p role="status" className="text-sm text-gray-300">{t('status.loading')}</p> :
        query.isError ? <p role="alert" className="text-sm text-amber-200">{t('parameters.loadError')}</p> :
          <div className="max-w-2xl space-y-5">
            {query.data.planet && <PlanetEditor world={world} branch={branch} settings={query.data.planet} />}
            <GridEditor world={world} branch={branch} settings={query.data} />
          </div>}
    </section>
  )
}
