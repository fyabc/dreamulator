import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import { worldParametersKey, type WorldParameters } from '../../api/worldParameters'
import { projectKey } from '../../projects/projectStore'

function GridEditor({ world, branch, settings }: { world: string; branch: string | null; settings: WorldParameters }) {
  const { t, i18n } = useTranslation('worlds')
  const client = useQueryClient()
  const [draft, setDraft] = useState<{ value: string; revision: string } | null>(null)
  const value = draft?.value ?? String(settings.num_cells ?? '')
  const cells = Number(value)
  const valid = value.trim() !== '' && Number.isSafeInteger(cells) && cells >= settings.min_cells && cells <= settings.max_cells
  const save = useMutation({
    mutationFn: (revision: string) => api.saveWorldParameters(world, branch, { num_cells: cells, revision }),
    onSuccess: updated => {
      client.setQueryData(worldParametersKey(world, branch), updated)
      setDraft(null)
      void client.invalidateQueries({ queryKey: ['buildGrid', world, branch] })
      void client.invalidateQueries({ queryKey: ['world', world] })
      void client.invalidateQueries({ queryKey: projectKey(world) })
    },
  })
  const changedElsewhere = (draft && draft.revision !== settings.revision) ||
    (save.error instanceof ApiError && save.error.status === 409 && save.error.message.includes('since it was opened')) ||
    (save.error instanceof DOMException && save.error.name === 'InvalidStateError')
  const busy = save.error instanceof ApiError && save.error.status === 409 && save.error.message.includes('already active')
  const format = (count: number) => count.toLocaleString(i18n.resolvedLanguage)

  if (settings.read_only || !settings.revision) return (
    <div className="space-y-2 text-sm text-gray-300">
      {settings.num_cells !== null && <p>{t('parameters.configured', { cells: format(settings.num_cells) })}</p>}
      <p>{t(`parameters.readOnly.${settings.read_only ?? 'unavailable'}`)}</p>
    </div>
  )

  return (
    <form className="max-w-2xl space-y-4" onSubmit={event => {
      event.preventDefault()
      if (valid && !changedElsewhere && cells !== settings.num_cells && !save.isPending) {
        save.mutate(draft?.revision ?? settings.revision!)
      }
    }}>
      <div className="space-y-2">
        <label htmlFor="world-grid-cells" className="block font-medium text-gray-100">{t('parameters.grid')}</label>
        <p id="world-grid-help" className="max-w-prose text-sm leading-relaxed text-gray-300">{t('parameters.help')}</p>
        <div className="flex flex-wrap items-center gap-3">
          <input id="world-grid-cells" type="number" required step={1} min={settings.min_cells} max={settings.max_cells}
            value={value} disabled={save.isPending} aria-describedby="world-grid-help world-grid-range"
            onChange={event => {
              save.reset()
              setDraft({ value: event.target.value, revision: draft?.revision ?? settings.revision! })
            }}
            className="min-h-11 w-40 rounded-md border border-space-border bg-space-bg px-3 text-gray-100 tabular-nums focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan" />
          <span id="world-grid-range" className="text-sm text-gray-300">
            {t('parameters.range', { min: format(settings.min_cells), max: format(settings.max_cells) })}
          </span>
        </div>
      </div>
      {settings.source && <p className="text-sm text-gray-300">{t('parameters.source')}{' '}
        <code className="break-all text-xs text-gray-200">{settings.source}</code>
      </p>}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <button type="submit" disabled={!valid || !!changedElsewhere || cells === settings.num_cells || save.isPending}
          className="min-h-11 rounded-md border border-neon-cyan/40 bg-neon-cyan/15 px-4 font-medium text-neon-cyan hover:bg-neon-cyan/25 focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan disabled:opacity-50">
          {t(save.isPending ? 'parameters.saving' : 'parameters.save')}
        </button>
        {(draft || save.isError) && <button type="button" disabled={save.isPending}
          className="min-h-11 rounded px-2 text-sm text-gray-200 underline underline-offset-4 focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan"
          onClick={() => { setDraft(null); save.reset(); void client.invalidateQueries({ queryKey: worldParametersKey(world, branch) }) }}>
          {t('parameters.reload')}
        </button>}
      </div>
      {changedElsewhere ? <p role="alert" className="text-sm text-amber-200">{t('parameters.conflict')}</p> :
        save.isError ? <p role="alert" className="text-sm text-amber-200">{t(busy ? 'parameters.busy' : 'parameters.error')}</p> :
          save.isSuccess && <p role="status" className="text-sm text-green-200">{t('parameters.saved')}</p>}
    </form>
  )
}

export default function WorldParametersPanel({ world, branch }: { world: string; branch: string | null }) {
  const { t } = useTranslation('worlds')
  const query = useQuery({ queryKey: worldParametersKey(world, branch),
    queryFn: () => api.getWorldParameters(world, branch), retry: false })
  return (
    <section aria-labelledby="world-parameters-title" className="space-y-4 rounded-xl border border-space-border bg-space-panel p-4 sm:p-6">
      <header className="space-y-1">
        <h2 id="world-parameters-title" className="text-lg font-semibold text-gray-100">{t('parameters.title')}</h2>
        <p className="max-w-prose text-sm leading-relaxed text-gray-300">
          {t(query.data?.revision && !query.data.read_only ? 'parameters.intro' : 'parameters.introReadOnly')}
        </p>
        <p className="text-sm text-gray-300">{t('parameters.scope', { world, branch: branch ?? t('label.baseWorld') })}</p>
        {isStaticMode() && query.data && !query.data.read_only && <p className="text-sm text-gray-300">{t('parameters.browser')}</p>}
      </header>
      {query.isPending ? <p role="status" className="text-sm text-gray-300">{t('status.loading')}</p> :
        query.isError ? <p role="alert" className="text-sm text-amber-200">{t('parameters.loadError')}</p> :
          <GridEditor world={world} branch={branch} settings={query.data} />}
    </section>
  )
}
