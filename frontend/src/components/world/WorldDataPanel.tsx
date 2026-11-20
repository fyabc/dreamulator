import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import ImportProjectElevation from '../projects/ImportProjectElevation'
import ProjectElevationView from '../projects/ProjectElevationView'
import { projectButton } from '../projects/SaveProjectResult'
import { projectBytes } from '../../projects/elevationProject'
import { deleteProject, getProject, projectKey, projectsKey, publishedWorld, removeProjectLayer, updateProject } from '../../projects/projectStore'
import { exportWorldData } from '../../projects/worldDataArchive'
import { downloadBlob } from '../../utils/downloadBlob'

export default function WorldDataPanel({ id, published }: { id: string; published: boolean }) {
  const { t, i18n } = useTranslation('worlds', { keyPrefix: 'worldData' })
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [search, setSearch] = useSearchParams()
  const [exportError, setExportError] = useState(false)
  const query = useQuery({ queryKey: projectKey(id), queryFn: () => getProject(id), retry: false })
  const remove = useMutation({ mutationFn: (layerId: string) => updateProject(id, (world) => removeProjectLayer(world, layerId)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: projectsKey }) })
  const erase = useMutation({ mutationFn: () => deleteProject(id), onSuccess: async () => {
    if (!published) navigate('/worlds')
    await queryClient.invalidateQueries({ queryKey: projectsKey })
  } })
  const world = query.data ?? (published && query.isSuccess ? publishedWorld(id) : null)
  const selected = world?.layers.find((layer) => layer.id === search.get('layer')) ?? world?.layers[0]
  const source = selected?.kind === 'elevation-source' ? selected : world?.layers.find(
    (layer) => layer.kind === 'elevation-source' && layer.id === selected?.sourceId)
  const busy = remove.isPending || erase.isPending
  const layerSearch = (layerId: string) => {
    const params = new URLSearchParams(search)
    params.set('tab', 'data')
    params.set('layer', layerId)
    return params
  }
  const bytes = world ? projectBytes(world) : 0
  const size = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 }).format(bytes >= 1e6 ? bytes / 1e6 : bytes / 1e3)

  if (query.isPending) return <p role="status">{t('loading')}</p>
  if (!world || query.isError) return <p role="alert" className="text-red-300">{t('unreadable')}</p>
  return <section className="space-y-4 rounded border border-space-border bg-space-panel p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 className="text-xl font-semibold">{t('title')}</h2>
      <div className="flex flex-wrap gap-2 text-sm">
        <button type="button" className={projectButton} disabled={busy || !world.layers.length} onClick={() => {
          setExportError(false)
          try { downloadBlob(exportWorldData(world), `${world.id}-world-data.tar`) }
          catch { setExportError(true) }
        }}>{t('export')}</button>
        <button type="button" className={projectButton} disabled={busy || (published && !world.layers.length)}
          onClick={() => { if (window.confirm(t(published ? 'confirmClear' : 'confirmDelete', { name: world.name }))) erase.mutate() }}>
          {t(published ? 'clear' : 'deleteWorld')}
        </button>
      </div>
    </div>
    <p className="text-sm text-gray-400">{t(published ? 'publishedHelp' : 'localHelp')}</p>
    <p className="text-sm text-gray-400">{t('usage', { size: `${size} ${bytes >= 1e6 ? 'MB' : 'kB'}` })}</p>
    {(erase.isError || remove.isError || exportError) && <p role="alert" className="text-red-300">{t(exportError ? 'exportFailed' : 'deleteFailed')}</p>}
    <div className="grid gap-3 lg:grid-cols-[minmax(16rem,1fr)_minmax(0,3fr)]">
      <aside className="min-w-0 space-y-3">
        <ImportProjectElevation world={world} onSaved={(layerId) => setSearch(layerSearch(layerId), { replace: true })} />
        <h3 className="text-sm font-medium">{t('layers')}</h3>
        {!world.layers.length && <p className="text-sm text-gray-400">{t('noLayers')}</p>}
        <ul className="space-y-2 text-sm">{world.layers.map((layer) => {
          const inUse = world.layers.some((other) => other.kind === 'elevation-result' && other.sourceId === layer.id)
          const input = layer.kind === 'elevation-source' ? layer : world.layers.find((item) => item.id === layer.sourceId)
          const location = input?.kind === 'elevation-source' ? input.location : undefined
          return <li key={layer.id} className="flex flex-wrap justify-between gap-2 rounded border border-space-border p-2">
            <div className="min-w-0">
              <Link to={`?${layerSearch(layer.id)}`} aria-current={layer.id === selected?.id ? 'true' : undefined}
                className={`break-all hover:underline ${layer.id === selected?.id ? 'font-semibold text-neon-cyan' : 'text-gray-200'}`}>{layer.name}</Link>
              {location && <p className="text-xs text-gray-400">{t('location', { planet: location.planet, branch: location.branch ?? t('mainBranch') })}</p>}
            </div>
            <button type="button" className={projectButton} disabled={busy || inUse} title={inUse ? t('sourceInUse') : undefined}
              aria-label={t('deleteLayerNamed', { name: layer.name })}
              onClick={() => { if (window.confirm(t('confirmLayerDelete', { name: layer.name }))) remove.mutate(layer.id) }}>{t('deleteLayer')}</button>
          </li>
        })}</ul>
      </aside>
      {selected && source?.kind === 'elevation-source' && <ProjectElevationView key={selected.id} projectId={id} layer={selected} source={source} />}
    </div>
  </section>
}
