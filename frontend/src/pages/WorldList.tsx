import { useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { isStaticMode } from '../api/mode'
import { deleteProject, listProjects, projectKey, projectsKey, restoreWorld, worldDataPath, worldOverviewPath } from '../projects/projectStore'
import { heightmapMapPath } from '../projects/heightmapWorld'
import WorldSourceBadge from '../components/world/WorldSourceBadge'

const linkClass = 'atlas-tool-button min-h-11 text-sm focus-visible:outline focus-visible:outline-neon-cyan disabled:opacity-50'
const deleteClass = 'min-h-11 rounded px-3 text-sm text-red-300 hover:underline focus-visible:outline focus-visible:outline-red-300 disabled:opacity-50'

function WorldDescription({ id }: { id: string }) {
  const { data: description } = useQuery({
    queryKey: ['world', id],
    queryFn: () => api.getWorld(id),
    select: world => typeof world?.metadata?.description === 'string' ? world.metadata.description.trim() : '',
    retry: false,
  })
  if (!description || description === id) return null
  return <p title={description} className="mt-1 truncate text-sm text-gray-400">{description}</p>
}

export default function WorldList() {
  const { t, i18n } = useTranslation('worlds')
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const importInput = useRef<HTMLInputElement>(null)
  const staticMode = isStaticMode()

  const catalog = useQuery({ queryKey: ['worlds'], queryFn: api.listWorlds })
  const projects = useQuery({ queryKey: projectsKey, queryFn: listProjects, enabled: staticMode, retry: false })
  const restore = useMutation({ mutationFn: async (file: File) => {
    const magic = new Uint8Array(await file.slice(0, 2).arrayBuffer())
    if (magic[0] === 31 && magic[1] === 139) return (await api.restoreBrowserCreation(file)).id
    const { readWorldBackup } = await import('../projects/worldDataArchive')
    const backup = await readWorldBackup(file)
    if (!backup.published && (catalog.data ?? await api.listWorlds()).some(id => id.toLowerCase() === backup.id.toLowerCase())) {
      throw new Error(t('worldData.collision'))
    }
    return restoreWorld(backup)
  }, onSuccess: async id => {
    await queryClient.invalidateQueries({ queryKey: projectsKey })
    navigate(worldOverviewPath(id))
  } })
  const erase = useMutation({ mutationFn: ({ id, browser }: { id: string; browser: boolean }) =>
    browser ? deleteProject(id) : api.deleteWorld(id),
  onSuccess: async (_, { id, browser }) => {
    if (browser) queryClient.removeQueries({ queryKey: projectKey(id), exact: true })
    await queryClient.invalidateQueries({ queryKey: browser ? projectsKey : ['worlds'] })
  } })

  if (searchParams.get('create') === '1') return <Navigate to="/new-world?start=template" replace />

  const published = catalog.data ?? []
  const publishedIds = new Set(published.map(id => id.toLowerCase()))
  const local = projects.data?.filter(project => !project.published && !publishedIds.has(project.id.toLowerCase())) ?? []
  const offline = projects.data?.filter(project => project.published && !publishedIds.has(project.id.toLowerCase())) ?? []
  const entries = [
    ...local.map(project => ({ id: project.id, name: project.name, source: 'browser' as const,
      map: project.hasMap ? heightmapMapPath(project.id) : null })),
    ...published.map(id => ({ id, name: id, source: 'catalog' as const, map: `${worldOverviewPath(id)}/map` })),
    ...(!catalog.isPending ? offline.map(project => ({ id: project.id, name: project.name,
      source: 'offline' as const, map: null })) : []),
  ]
  const busy = restore.isPending || erase.isPending
  const bytes = projects.data?.reduce((total, project) => total + project.bytes, 0)
  const size = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 }).format((bytes ?? 0) / 1e6)
  const loading = catalog.isLoading || projects.isLoading

  return <div className="mx-auto min-h-screen max-w-5xl px-4 py-6 sm:px-6 sm:py-8">
    <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-3xl font-bold text-neon-cyan">{t('title.list')}</h1>
      <div className="flex flex-wrap items-center gap-2">
        {staticMode && <>
          <button type="button" className={linkClass} disabled={busy} onClick={() => importInput.current?.click()}>
            {t('worldData.import')}
          </button>
          <input ref={importInput} type="file" hidden accept=".tar,.gz,.dreamulator" onChange={event => {
            const file = event.currentTarget.files?.[0]
            event.currentTarget.value = ''
            if (file && !busy) restore.mutate(file)
          }} />
        </>}
        <Link to="/new-world" className="atlas-primary text-sm">
          {t('action.newWorld')}
        </Link>
      </div>
    </header>
    {loading && <p role="status" className="mb-3 text-sm text-gray-300">{t('status.loading')}</p>}
    {restore.isPending && <p role="status">{t('worldData.saving')}</p>}
    {erase.isPending && <p role="status">{t('worldData.deleting')}</p>}
    {catalog.error && <p role="alert" className="mb-3 text-sm text-red-300">{t('status.loadError')}: {catalog.error.message}</p>}
    {projects.isError && <p role="alert" className="mb-3 text-sm text-red-300">{t('worldData.unreadable')}</p>}
    {restore.error && <p role="alert" className="mb-3 text-sm text-red-300">{t('worldData.importFailed')} {restore.error.message}</p>}
    {erase.isError && <p role="alert" className="mb-3 text-sm text-red-300">{t('worldData.deleteFailed')}</p>}

    {entries.length > 0 ? <ul className="divide-y divide-space-border border-y border-space-border">
      {entries.map(({ id, name, source, map }) => {
        const overview = worldOverviewPath(id)
        const target = source === 'offline' ? worldDataPath(id) : overview
        return <li key={id} className="flex flex-col gap-x-5 gap-y-2 py-3 sm:flex-row sm:items-center">
          <div className="min-w-0 flex-1">
            <Link to={target} className="block break-words font-semibold text-gray-100 hover:text-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan">
              {name}
            </Link>
            {staticMode && <WorldSourceBadge source={source === 'catalog' ? 'published' : source} />}
            {source === 'catalog' && <WorldDescription id={id} />}
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:w-80 sm:shrink-0">
            {map && <Link className={linkClass} to={map}>{t('action.openWorldMap')}</Link>}
            {source !== 'offline' && <Link className={linkClass} to={overview}>{t('action.worldOverview')}</Link>}
            {source !== 'catalog' && <Link className={linkClass} to={worldDataPath(id)}>{t('worldData.title')}</Link>}
            {(!staticMode || source === 'browser') && <button type="button" className={deleteClass} disabled={busy}
              onClick={() => {
                if (window.confirm(t(source === 'browser' ? 'worldData.confirmDelete' : 'confirm.deleteWorld', { name }))) {
                  erase.mutate({ id, browser: source === 'browser' })
                }
              }}>{t('action.deleteWorld')}</button>}
          </div>
        </li>
      })}
    </ul> : !loading && !catalog.error && !projects.isError &&
      <p className="py-6 text-gray-400">{t(staticMode ? 'status.noWorldsStatic' : 'status.noWorlds')}</p>}
    {bytes !== undefined && bytes > 0 && <p className="mt-4 text-sm text-gray-400">{t('worldData.usage', { size: `${size} MB` })}</p>}
  </div>
}
