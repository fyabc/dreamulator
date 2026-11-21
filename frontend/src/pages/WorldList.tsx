import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { isStaticMode } from '../api/mode'
import { listProjects, projectsKey, restoreWorld, worldDataPath } from '../projects/projectStore'

export default function WorldList() {
  const { t } = useTranslation('worlds')
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const staticMode = isStaticMode()

  const { data: worlds, isLoading, error } = useQuery({
    queryKey: ['worlds'],
    queryFn: api.listWorlds,
  })

  const deleteMutation = useMutation({
    mutationFn: (name: string) => api.deleteWorld(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['worlds'] })
    },
  })

  if (searchParams.get('create') === '1') return <Navigate to="/new-world?start=template" replace />

  return (
    <div className="relative min-h-screen">

      <div className="relative z-10 px-6 py-8">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-neon-cyan neon-glow-subtle">
            {t('title.list')}
          </h1>
            <Link
              to="/new-world"
              className="px-4 py-2 rounded-lg font-medium transition-all bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 hover:shadow-[0_0_12px_rgba(0,212,255,0.15)]"
            >
              + {t('action.newWorld')}
            </Link>
        </div>

        {staticMode && <BrowserWorlds published={worlds} />}

        {isLoading && <div className="text-center py-12 text-gray-400">{t('status.loading')}</div>}

        {error && (
          <div className="text-center py-12 text-red-400">{t('status.loadError')}: {error.message}</div>
        )}

        {!isLoading && !error && worlds && worlds.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {worlds.map((worldName) => (
              <div key={worldName} className="glass-panel p-6">
                <Link to={`/worlds/${worldName}`} className="block">
                  <h3 className="text-xl font-semibold mb-2 text-neon-cyan neon-glow-subtle">
                    {worldName}
                  </h3>
                </Link>
                <div className="flex gap-2 mt-4">
                  <Link
                    to={`/worlds/${worldName}`}
                    className="text-sm px-3 py-1.5 rounded transition-all bg-space-surface text-gray-300 border space-border hover:border-neon-cyan/30 hover:text-neon-cyan"
                  >
                    {t('action.openWorld')}
                  </Link>
                  {!staticMode && (
                    <button
                      onClick={() => {
                        if (confirm(t('confirm.deleteWorld', { name: worldName }))) {
                          deleteMutation.mutate(worldName)
                        }
                      }}
                      className="text-sm px-3 py-1.5 rounded transition-all bg-red-900/30 text-red-400 border border-red-500/20 hover:bg-red-900/50"
                    >
                      {t('action.deleteWorld')}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {!isLoading && !error && worlds && worlds.length === 0 && (
          <div className="text-center py-12">
            <p className="text-lg mb-4 text-gray-400">
              {staticMode ? t('status.noWorldsStatic') : t('status.noWorlds')}
            </p>
            {!staticMode && (
              <Link
                to="/new-world"
                className="px-6 py-3 rounded-lg font-medium transition-all bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25"
              >
                {t('action.createFirstWorld')}
              </Link>
            )}
          </div>
        )}

      </div>
    </div>
  )
}

function BrowserWorlds({ published }: { published?: string[] }) {
  const { t, i18n } = useTranslation('worlds', { keyPrefix: 'worldData' })
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const data = useQuery({ queryKey: projectsKey, queryFn: listProjects, retry: false })
  const open = async (id: string) => {
    await queryClient.invalidateQueries({ queryKey: projectsKey })
    navigate(worldDataPath(id))
  }
  const restore = useMutation({ mutationFn: async (file: File) => {
    const magic = new Uint8Array(await file.slice(0, 2).arrayBuffer())
    if (magic[0] === 31 && magic[1] === 139) {
      return (await api.restoreBrowserCreation(file)).id
    }
    const { readWorldBackup } = await import('../projects/worldDataArchive')
    return restoreWorld(await readWorldBackup(file))
  }, onSuccess: open })
  const busy = restore.isPending
  const local = data.data?.filter((world) => !world.published || !published?.includes(world.id)) ?? []
  const bytes = data.data?.reduce((sum, world) => sum + world.bytes, 0)
  const size = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 }).format((bytes ?? 0) / 1e6)
  return <section className="mb-8 space-y-4 rounded border border-space-border bg-space-panel p-4">
    <h2 className="text-xl font-semibold">{t('browserWorlds')}</h2>
    <label className="flex flex-wrap items-center gap-2 text-sm">{t('import')}
      <input type="file" className="max-w-full" accept=".tar,.gz,.dreamulator" disabled={busy} onChange={(event) => {
        const file = event.currentTarget.files?.[0]
        event.currentTarget.value = ''
        if (file && !busy) restore.mutate(file)
      }} />
    </label>
    {busy && <p role="status">{t('saving')}</p>}
    {(data.isError || restore.isError) && <p role="alert" className="text-red-300">
      {t(restore.isError ? 'importFailed' : 'unreadable')}{restore.isError && ` ${restore.error.message}`}
    </p>}
    {bytes !== undefined && <p className="text-sm text-gray-400">{t('usage', { size: `${size} MB` })}</p>}
    {!!local.length && <ul className="space-y-1 text-sm">{local.map((world) => <li key={world.id}>
      <Link className="break-all text-neon-cyan hover:underline" to={worldDataPath(world.id)}>{world.name}</Link>
    </li>)}</ul>}
  </section>
}
