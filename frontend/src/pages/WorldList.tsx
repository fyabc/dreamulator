import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { isStaticMode } from '../api/mode'
import { createProject, listProjects, projectsKey, restoreWorld, worldDataPath } from '../projects/projectStore'

export default function WorldList() {
  const { t } = useTranslation('worlds')
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  // `?create=1` (the home page's "create from a template") opens the dialog directly.
  const [showCreateDialog, setShowCreateDialog] = useState(() => searchParams.get('create') === '1' && !isStaticMode())
  const [newWorldName, setNewWorldName] = useState('')
  const [newWorldTemplate, setNewWorldTemplate] = useState('minimal')
  const staticMode = isStaticMode()

  const { data: worlds, isLoading, error } = useQuery({
    queryKey: ['worlds'],
    queryFn: api.listWorlds,
  })

  const createMutation = useMutation({
    mutationFn: ({ name, template }: { name: string; template: string }) =>
      api.createWorld(name, template),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['worlds'] })
      setShowCreateDialog(false)
      setNewWorldName('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (name: string) => api.deleteWorld(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['worlds'] })
    },
  })

  const handleCreate = () => {
    if (newWorldName.trim()) {
      createMutation.mutate({ name: newWorldName, template: newWorldTemplate })
    }
  }

  return (
    <div className="relative min-h-screen">

      <div className="relative z-10 px-6 py-8">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-neon-cyan neon-glow-subtle">
            {t('title.list')}
          </h1>
          {!staticMode && (
            <button
              onClick={() => setShowCreateDialog(true)}
              className="px-4 py-2 rounded-lg font-medium transition-all bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 hover:shadow-[0_0_12px_rgba(0,212,255,0.15)]"
            >
              + {t('action.newWorld')}
            </button>
          )}
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
              <button
                onClick={() => setShowCreateDialog(true)}
                className="px-6 py-3 rounded-lg font-medium transition-all bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25"
              >
                {t('action.createFirstWorld')}
              </button>
            )}
          </div>
        )}

        {showCreateDialog && !staticMode && (
          <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 backdrop-blur-sm">
            <div className="bg-space-panel border border-space-border rounded-xl p-6 w-full max-w-md shadow-[0_0_40px_rgba(0,212,255,0.08)]">
              <h2 className="text-2xl font-bold mb-4 text-neon-cyan neon-glow-subtle">
                {t('dialog.createWorldTitle')}
              </h2>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-2 text-gray-400">
                    {t('label.worldName')}
                  </label>
                  <input
                    type="text"
                    value={newWorldName}
                    onChange={(e) => setNewWorldName(e.target.value)}
                    placeholder="my_world"
                    className="w-full bg-space-bg border border-space-border rounded-lg px-4 py-2 text-white focus:outline-none focus:border-neon-cyan transition-colors"
                    autoFocus
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium mb-2 text-gray-400">
                    {t('label.template')}
                  </label>
                  <select
                    value={newWorldTemplate}
                    onChange={(e) => setNewWorldTemplate(e.target.value)}
                    className="w-full bg-space-bg border border-space-border rounded-lg px-4 py-2 text-white focus:outline-none focus:border-neon-cyan transition-colors"
                  >
                    <option value="minimal">Minimal</option>
                    <option value="earthlike">Earth-like</option>
                  </select>
                </div>

                {createMutation.error && (
                  <div className="text-red-400 text-sm">
                    {t('status.createError')}: {createMutation.error.message}
                  </div>
                )}

                <div className="flex gap-3 pt-4">
                  <button
                    onClick={handleCreate}
                    disabled={createMutation.isPending}
                    className="flex-1 px-4 py-2 rounded-lg font-medium transition-all bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 disabled:opacity-50"
                  >
                    {createMutation.isPending ? t('action.creating') : t('action.create')}
                  </button>
                  <button
                    onClick={() => setShowCreateDialog(false)}
                    className="flex-1 px-4 py-2 rounded-lg font-medium transition-all bg-space-surface text-gray-300 border space-border hover:border-gray-500"
                  >
                    {t('action.cancel')}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function BrowserWorlds({ published }: { published?: string[] }) {
  const { t, i18n } = useTranslation('worlds', { keyPrefix: 'worldData' })
  const [name, setName] = useState('')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const data = useQuery({ queryKey: projectsKey, queryFn: listProjects, retry: false })
  const open = async (id: string) => {
    await queryClient.invalidateQueries({ queryKey: projectsKey })
    navigate(worldDataPath(id))
  }
  const create = useMutation({ mutationFn: createProject, onSuccess: open })
  const restore = useMutation({ mutationFn: async (file: File) => {
    const { readWorldBackup } = await import('../projects/worldDataArchive')
    return restoreWorld(await readWorldBackup(file))
  }, onSuccess: open })
  const busy = create.isPending || restore.isPending
  const local = data.data?.filter((world) => !world.published || !published?.includes(world.id)) ?? []
  const bytes = data.data?.reduce((sum, world) => sum + world.bytes, 0)
  const size = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 }).format((bytes ?? 0) / 1e6)
  return <section className="mb-8 space-y-4 rounded border border-space-border bg-space-panel p-4">
    <h2 className="text-xl font-semibold">{t('browserWorlds')}</h2>
    <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => {
      event.preventDefault()
      if (!busy && name.trim()) create.mutate(name)
    }}>
      <label className="flex flex-col gap-1 text-sm">{t('name')}
        <input className="rounded border border-space-border bg-space-bg px-2 py-1" value={name} maxLength={200}
          disabled={busy} onChange={(event) => setName(event.currentTarget.value)} />
      </label>
      <button className="rounded border border-space-border px-2 py-1 text-neon-cyan disabled:opacity-50" disabled={busy || !name.trim()}>{t('new')}</button>
    </form>
    <label className="flex flex-wrap items-center gap-2 text-sm">{t('import')}
      <input type="file" className="max-w-full" accept=".tar,.dreamulator" disabled={busy} onChange={(event) => {
        const file = event.currentTarget.files?.[0]
        event.currentTarget.value = ''
        if (file && !busy) restore.mutate(file)
      }} />
    </label>
    {busy && <p role="status">{t('saving')}</p>}
    {(data.isError || create.isError || restore.isError) && <p role="alert" className="text-red-300">
      {t(restore.isError ? 'importFailed' : create.isError ? 'saveFailed' : 'unreadable')}
    </p>}
    {bytes !== undefined && <p className="text-sm text-gray-400">{t('usage', { size: `${size} MB` })}</p>}
    {!!local.length && <ul className="space-y-1 text-sm">{local.map((world) => <li key={world.id}>
      <Link className="break-all text-neon-cyan hover:underline" to={worldDataPath(world.id)}>{world.name}</Link>
    </li>)}</ul>}
  </section>
}
