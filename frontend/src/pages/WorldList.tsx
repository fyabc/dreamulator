import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { isStaticMode } from '../api/mode'
import StarfieldBackground from '../components/StarfieldBackground'

export default function WorldList() {
  const { t } = useTranslation('worlds')
  const queryClient = useQueryClient()
  const [showCreateDialog, setShowCreateDialog] = useState(false)
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
      <StarfieldBackground />

      <div className="relative z-10 px-6 py-8">
        <div className="flex justify-between items-center mb-8">
          <h1 className="text-3xl font-bold text-neon-cyan neon-glow-subtle">
            {staticMode ? t('title.browse') : t('title.list')}
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
