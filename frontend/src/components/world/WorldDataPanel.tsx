import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import AtlasIcon from '../AtlasIcon'
import ImportProjectElevation from '../projects/ImportProjectElevation'
import { projectButton } from '../projects/SaveProjectResult'
import { elevationSource, projectBytes } from '../../projects/elevationProject'
import { deleteProject, getProject, projectKey, projectRegionPath, projectsKey, publishedWorld, removeProjectLayer, updateProject } from '../../projects/projectStore'
import { exportWorldData } from '../../projects/worldDataArchive'
import { downloadBlob } from '../../utils/downloadBlob'

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
  const query = useQuery({ queryKey: projectKey(id), queryFn: () => getProject(id), retry: false })
  const remove = useMutation({ mutationFn: (layerId: string) => updateProject(id, (world) => removeProjectLayer(world, layerId)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: projectsKey }) })
  const erase = useMutation({ mutationFn: () => deleteProject(id), onSuccess: async () => {
    if (!published) navigate('/worlds')
    setExportError(false)
    await queryClient.invalidateQueries({ queryKey: projectsKey })
  } })
  const world = query.data ?? (published && query.isSuccess ? publishedWorld(id) : null)
  const busy = remove.isPending || erase.isPending
  const layerPath = (layerId: string) => projectRegionPath(id, layerId, search.get('branch'))

  if (query.isPending) return <p role="status">{t('loading')}</p>
  if (!world || query.isError) return <p role="alert" className="text-red-300">{t('unreadable')}</p>

  const hasLayers = world.layers.length > 0
  const overviewSearch = new URLSearchParams(search)
  for (const param of ['doc', 'layer', 'tab']) overviewSearch.delete(param)
  const formatNumber = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 })
  const bytes = projectBytes(world)
  const size = formatNumber.format(bytes >= 1e6 ? bytes / 1e6 : bytes / 1e3)

  return <div className="space-y-5">
    {published && <section aria-labelledby="published-data-heading"
      className="flex flex-wrap items-center justify-between gap-x-5 gap-y-1 border-b border-space-border pb-3">
      <div className="space-y-1">
        <h2 id="published-data-heading" className="text-sm font-semibold text-gray-200">{t('publishedData')}</h2>
        <p className="text-sm leading-relaxed text-gray-400">{t(publishedAvailable ? 'publishedHelp' : 'publishedUnavailable')}</p>
      </div>
      {publishedAvailable && <Link to={{ search: overviewSearch.toString() }}
        className="inline-flex min-h-11 items-center text-sm text-neon-cyan hover:underline">{t('openPublished')}</Link>}
    </section>}

    <section aria-labelledby="browser-data-heading" className="space-y-4">
      <header className="space-y-1">
        <h2 id="browser-data-heading" className="text-xl font-semibold text-gray-100">{t('browserData')}</h2>
        <p className="text-sm text-gray-400">{t('usage', { size: `${size} ${bytes >= 1e6 ? 'MB' : 'kB'}` })}</p>
      </header>
      <div className="max-w-2xl space-y-3">
        <h3 className="text-sm font-medium text-gray-200">{t('layers')}</h3>
        {hasLayers ? <ul className="divide-y divide-space-border border-y border-space-border text-sm">
          {world.layers.map((layer) => {
            const source = elevationSource(world.layers, layer)
            const span = source?.frame.window.extentKmX
            return <li key={layer.id}>
              <Link to={layerPath(layer.id)}
                className="flex min-h-11 items-center justify-between gap-3 px-3 py-2.5 text-gray-200 hover:bg-space-surface focus-visible:bg-space-surface">
                <span className="min-w-0 space-y-1">
                  <span className="block break-words font-medium">{layer.name}</span>
                  <span className="block text-xs text-gray-400">{t(layer.kind === 'elevation-source' ? 'sourceLayer' : 'resultLayer')}
                    {span !== undefined && <> · {t('layerSpan', { span: formatNumber.format(span) })}</>}
                  </span>
                </span>
                <AtlasIcon name="arrow" className="size-4 text-neon-cyan" />
              </Link>
            </li>
          })}
        </ul> : <p role="status" className="text-sm text-gray-400">{t('noLayers')}</p>}
        <ImportProjectElevation world={world} onSaved={(savedId) => navigate(layerPath(savedId))} />
      </div>
    </section>

    <section aria-labelledby="world-backup-heading" className="space-y-2 border-t border-space-border pt-4 text-sm">
      <h2 id="world-backup-heading" className="font-semibold text-gray-200">{t('backup')}</h2>
      <p className="max-w-2xl leading-relaxed text-gray-400">{t(published ? 'publishedBackupHelp' : 'localHelp')}</p>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {hasLayers && <button type="button" className={`${projectButton} min-h-11 px-3`} disabled={busy} onClick={() => {
          setExportError(false)
          try { downloadBlob(exportWorldData(world), `${world.id}-world-data.tar`) }
          catch { setExportError(true) }
        }}>{t('export')}</button>}
        <Link to="/worlds" className="inline-flex min-h-11 items-center text-neon-cyan hover:underline">{t('restoreFromWorlds')}</Link>
      </div>
      {exportError && <p role="alert" className="text-red-300">{t('exportFailed')}</p>}
    </section>

    {(!published || hasLayers) && <details className="space-y-3 border-t border-space-border pt-2 text-sm">
      <summary className="min-h-11 cursor-pointer content-center font-medium text-gray-300">{t('manageStorage')}</summary>
      {hasLayers && <ul className="max-w-2xl divide-y divide-space-border border-y border-space-border">
        {world.layers.map((layer) => {
          const inUse = world.layers.some((other) => other.kind === 'elevation-result' && other.sourceId === layer.id)
          return <li key={layer.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-1">
            <div className="min-w-0 flex-1 basis-40 text-gray-300">
              <p className="break-words">{layer.name}</p>
              {inUse && <p className="text-xs text-gray-400">{t('sourceInUse')}</p>}
            </div>
            <button type="button" className="min-h-11 px-2 text-red-300 hover:underline disabled:text-gray-500 disabled:no-underline"
              disabled={busy || inUse} aria-label={t('deleteLayerNamed', { name: layer.name })}
              onClick={() => { if (window.confirm(t('confirmLayerDelete', { name: layer.name }))) remove.mutate(layer.id) }}>{t('deleteLayer')}</button>
          </li>
        })}
      </ul>}
      <p className="max-w-2xl text-gray-400">{t(published ? 'clearHelp' : 'deleteWorldHelp', { name: world.name })}</p>
      <button type="button" className="min-h-11 rounded border border-space-border px-3 text-red-300 hover:border-red-300 disabled:opacity-50"
        disabled={busy} onClick={() => { if (window.confirm(t(published ? 'confirmClear' : 'confirmDelete', { name: world.name }))) erase.mutate() }}>
        {t(published ? 'clear' : 'deleteWorld')}
      </button>
      {(erase.isError || remove.isError) && <p role="alert" className="text-red-300">{t('deleteFailed')}</p>}
    </details>}
  </div>
}
