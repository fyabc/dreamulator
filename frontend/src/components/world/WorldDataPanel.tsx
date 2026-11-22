import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import AtlasIcon from '../AtlasIcon'
import { isStaticMode } from '../../api/mode'
import { temperatureTrialMapPath } from '../../playground/temperatureDraft'
import { projectButton } from '../projects/SaveProjectResult'
import { elevationSource, projectBytes } from '../../projects/elevationProject'
import { deleteProject, getProject, projectKey, projectRegionPath, projectsKey, publishedWorld, removeProjectLayer, restoreWorld, updateProject } from '../../projects/projectStore'
import { downloadWorldBackup, readWorldBackup } from '../../projects/worldDataArchive'
import SavedClimateTrials from './SavedClimateTrials'
import { tutorialMilestone } from '../../tutorial/tutorialProgress'
import { clearTerrainModelCache, readTerrainModelCacheBytes } from '../../viewers/packs/terrainModelCache'

function formatModelCacheSize(bytes: number, language: string) {
  const [unit, divisor] = bytes >= 1e9 ? ['gigabyte', 1e9] as const : ['megabyte', 1e6] as const
  return new Intl.NumberFormat(language, { style: 'unit', unit, unitDisplay: 'short', maximumFractionDigits: 2 })
    .format(bytes / divisor)
}

export default function WorldDataPanel({ id, published, publishedAvailable }: {
  id: string
  published: boolean
  publishedAvailable: boolean
}) {
  const { t, i18n } = useTranslation('worlds', { keyPrefix: 'worldData' })
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [search] = useSearchParams()
  const [exportError, setExportError] = useState(false)
  const staticMode = isStaticMode()
  const query = useQuery({ queryKey: projectKey(id), queryFn: () => getProject(id), retry: false })
  const remove = useMutation({ mutationFn: (layerId: string) => updateProject(id, (world) => removeProjectLayer(world, layerId)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: projectsKey }) })
  const removeDraft = useMutation({ mutationFn: (draftId: string) => updateProject(id, project => ({ ...project,
    temperatureDrafts: project.temperatureDrafts?.filter(draft => draft.id !== draftId),
  })), onSuccess: () => queryClient.invalidateQueries({ queryKey: projectsKey }) })
  const restore = useMutation({ mutationFn: async (file: File) => {
    const backup = await readWorldBackup(file)
    if (!backup.published || backup.id !== id) throw new Error('Backup belongs to another world')
    await restoreWorld(backup)
  }, onSuccess: () => queryClient.invalidateQueries({ queryKey: projectsKey }) })
  const modelCache = useQuery({ queryKey: ['terrain-model-cache'], queryFn: readTerrainModelCacheBytes,
    enabled: staticMode, staleTime: 0, retry: false })
  const clearModels = useMutation({ mutationFn: clearTerrainModelCache,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['terrain-model-cache'] }) })
  const erase = useMutation({ mutationFn: () => deleteProject(id), onSuccess: async () => {
    if (!published) navigate('/worlds')
    setExportError(false)
    await queryClient.invalidateQueries({ queryKey: projectsKey })
  } })
  const world = query.data ?? (published && query.isSuccess ? publishedWorld(id) : null)
  const busy = remove.isPending || removeDraft.isPending || erase.isPending || restore.isPending
  const layerPath = (layerId: string) => projectRegionPath(id, layerId, search.get('branch'))

  if (query.isPending) return <p role="status">{t('loading')}</p>
  if (!world || query.isError) return <p role="alert" className="text-red-300">{t('unreadable')}</p>

  const hasLayers = world.layers.length > 0
  const drafts = world.temperatureDrafts ?? []
  const hasLocalData = !!world.creationSnapshot || hasLayers || drafts.length > 0 || (world.climateTrials?.length ?? 0) > 0
  const overviewSearch = new URLSearchParams(search)
  for (const param of ['doc', 'layer', 'tab']) overviewSearch.delete(param)
  const formatNumber = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 })
  const bytes = projectBytes(world)
  const size = formatNumber.format(bytes >= 1e6 ? bytes / 1e6 : bytes / 1e3)

  return <div className="space-y-5">
    {published && <section aria-labelledby="published-data-heading"
      className="flex flex-wrap items-center justify-between gap-x-5 gap-y-1 border-b border-space-border pb-3">
      <div className="space-y-1">
        <h2 id="published-data-heading" className="text-sm font-semibold text-gray-200">{t(staticMode ? 'publishedData' : 'serverData')}</h2>
        <p className="text-sm leading-relaxed text-gray-400">{t(!staticMode ? 'serverHelp' : publishedAvailable ? 'publishedHelp' : 'publishedUnavailable')}</p>
      </div>
      {publishedAvailable && <Link to={{ search: overviewSearch.toString() }}
        className="inline-flex min-h-11 items-center text-sm text-neon-cyan hover:underline">{t(staticMode ? 'openPublished' : 'openServer')}</Link>}
    </section>}

    <section aria-labelledby="browser-data-heading" className="space-y-4">
      <header className="space-y-1">
        <h2 id="browser-data-heading" className="text-xl font-semibold text-gray-100">{t('browserData')}</h2>
        <p className="text-sm text-gray-400">{t('usage', { size: `${size} ${bytes >= 1e6 ? 'MB' : 'kB'}` })}</p>
      </header>
      {world.creationSnapshot && <p className="text-sm text-gray-400">{t(world.creationKind === 'starter' ? 'storedSettings' : 'storedHeightmap')}</p>}
      {!hasLocalData && <p className="text-sm text-gray-400">{t('noLayers')}</p>}
      {hasLayers && <div className="max-w-2xl space-y-3">
        <h3 className="text-sm font-medium text-gray-200">{t('layers')}</h3>
        <ul className="divide-y divide-space-border border-y border-space-border text-sm">
          {world.layers.map((layer) => {
            const source = elevationSource(world.layers, layer)
            const span = source?.frame.window.extentKmX
            const inUse = world.layers.some(other => other.kind === 'elevation-result' && other.sourceId === layer.id)
            return <li key={layer.id} className="flex items-center gap-2">
              <Link to={layerPath(layer.id)}
                className="flex min-h-11 min-w-0 flex-1 items-center justify-between gap-3 px-3 py-2.5 text-gray-200 hover:bg-space-surface focus-visible:bg-space-surface">
                <span className="min-w-0 space-y-1">
                  <span className="block break-words font-medium">{layer.name}</span>
                  <span className="block text-xs text-gray-400">{t(layer.kind === 'elevation-source' ? 'sourceLayer' : 'resultLayer')}
                    {span !== undefined && <> · {t('layerSpan', { span: formatNumber.format(span) })}</>}
                  </span>
                </span>
                <AtlasIcon name="arrow" className="size-4 text-neon-cyan" />
              </Link>
              <button type="button" className="min-h-11 shrink-0 px-2 text-xs text-red-300 hover:underline disabled:text-gray-500 disabled:no-underline"
                disabled={busy || inUse} title={inUse ? t('sourceInUse') : undefined} aria-label={t('deleteLayerNamed', { name: layer.name })}
                onClick={() => { if (window.confirm(t('confirmLayerDelete', { name: layer.name }))) remove.mutate(layer.id) }}>{t('deleteLayer')}</button>
            </li>
          })}
        </ul>
        {remove.isError && <p role="alert" className="text-sm text-red-300">{t('deleteFailed')}</p>}
      </div>}
      {drafts.length > 0 && <div className="max-w-2xl space-y-2">
        <h3 className="text-sm font-medium text-gray-200">{t('temperatureDrafts')}</h3>
        <ul className="divide-y divide-space-border border-y border-space-border text-sm">
          {drafts.map(draft => <li key={draft.id} className="flex flex-wrap items-center gap-x-3 px-3 py-1">
            <Link to={temperatureTrialMapPath({ world: id, planet: draft.planet, branch: draft.branch }, draft.id)}
              className="flex min-h-11 min-w-0 flex-1 basis-48 flex-col justify-center break-words py-1.5 text-neon-cyan hover:underline">
              {draft.source}
              <span className="text-xs text-gray-400">{draft.branch || t('rootBranch')} · {new Date(draft.updatedAt).toLocaleString(i18n.language)}</span>
            </Link>
            <button type="button" className="min-h-11 px-2 text-red-300 hover:underline disabled:opacity-50" disabled={busy}
              aria-label={t('deleteDraftNamed', { name: draft.source })}
              onClick={() => { if (window.confirm(t('deleteDraftNamed', { name: draft.source }))) removeDraft.mutate(draft.id) }}>{t('deleteDraft')}</button>
          </li>)}
        </ul>
        {removeDraft.isError && <p role="alert" className="text-sm text-red-300">{t('deleteFailed')}</p>}
      </div>}
      {staticMode && !!world.climateTrials?.length && <SavedClimateTrials world={id} />}
    </section>
    {!staticMode && publishedAvailable && <SavedClimateTrials world={id} />}

    <section aria-labelledby="world-backup-heading" className="space-y-2 border-t border-space-border pt-4 text-sm">
      <h2 id="world-backup-heading" className="font-semibold text-gray-200">{t('backup')}</h2>
      <p className="max-w-2xl leading-relaxed text-gray-400">{t(published ? 'publishedBackupHelp' : 'localHelp')}</p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {hasLocalData && <button type="button" data-tutorial-anchor={world.creationSnapshot ? 'browserBackup' : undefined}
          className={`${projectButton} min-h-11 px-3`} disabled={busy} onClick={() => {
          setExportError(false)
          try {
            downloadWorldBackup(world)
            if (world.creationSnapshot) tutorialMilestone({ type: 'backup', world: id })
          }
          catch { setExportError(true) }
        }}>{t('export')}</button>}
        {staticMode ? <Link to="/worlds" className="inline-flex min-h-11 items-center text-neon-cyan hover:underline">{t('restoreFromWorlds')}</Link>
          : <label className="inline-flex min-h-11 cursor-pointer items-center text-neon-cyan hover:underline focus-within:outline">
            {t('restoreHere')}
            <input type="file" accept=".tar,.dreamulator" className="sr-only" disabled={busy} onChange={event => {
              const file = event.currentTarget.files?.[0]
              event.currentTarget.value = ''
              if (file) restore.mutate(file)
            }} />
          </label>}
      </div>
      {exportError && <p role="alert" className="text-red-300">{t('exportFailed')}</p>}
      {restore.isError && <p role="alert" className="text-red-300">{t('restoreHereFailed')}</p>}
      {restore.isSuccess && <p role="status" className="text-green-300">{t('restoredHere')}</p>}
      {!staticMode && <p className="max-w-2xl leading-relaxed text-gray-400">{t('serverSnapshotHelp')}</p>}
    </section>

    {staticMode && <section aria-labelledby="model-cache-heading" className="space-y-2 border-t border-space-border pt-4 text-sm">
      <h2 id="model-cache-heading" className="font-semibold text-gray-200">{t('modelCache')}</h2>
      <p className="max-w-2xl leading-relaxed text-gray-400">{t('modelCacheHelp')}</p>
      <p role="status">{modelCache.isPending ? t('modelCacheChecking')
        : modelCache.isError ? t('modelCacheUnavailable')
          : (modelCache.data ?? 0) === 0 ? t('modelCacheEmpty')
            : t('modelCacheSize', { size: formatModelCacheSize(modelCache.data ?? 0, i18n.language) })}</p>
      <button type="button" className="min-h-11 rounded border border-space-border px-3 text-red-300 hover:border-red-300 disabled:opacity-50"
        disabled={!modelCache.data || modelCache.isError || clearModels.isPending}
        onClick={() => { if (window.confirm(t('confirmModelCache'))) clearModels.mutate() }}>{t('clearModelCache')}</button>
      {clearModels.isSuccess && <p role="status" className="text-green-300">{t('modelCacheCleared')}</p>}
      {clearModels.isError && <p role="alert" className="text-red-300">{t('deleteFailed')}</p>}
    </section>}

    {(!published || hasLocalData) && <details className="space-y-3 border-t border-space-border pt-2 text-sm">
      <summary className="min-h-11 cursor-pointer content-center font-medium text-gray-300">{t('manageStorage')}</summary>
      <p className="max-w-2xl text-gray-400">{t(published ? 'clearHelp' : 'deleteWorldHelp', { name: world.name })}</p>
      <button type="button" className="min-h-11 rounded border border-space-border px-3 text-red-300 hover:border-red-300 disabled:opacity-50"
        disabled={busy} onClick={() => { if (window.confirm(t(published ? 'confirmClear' : 'confirmDelete', { name: world.name }))) erase.mutate() }}>
        {t(published ? 'clear' : 'deleteWorld')}
      </button>
      {erase.isError && <p role="alert" className="text-red-300">{t('deleteFailed')}</p>}
    </details>}
  </div>
}
