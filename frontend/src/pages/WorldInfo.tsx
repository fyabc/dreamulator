/**
 * WorldInfo — redirected to /worlds in App.tsx.  Kept as a thin wrapper
 * in case the redirect is ever removed; delegates rendering to the shared
 * LayerDag component instead of duplicating the DAG visualisation.
 */

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import StarfieldBackground from '../components/StarfieldBackground'
import LayerDag, { LAYER_LABELS } from '../components/LayerDag'

export default function WorldInfo() {
  const { t } = useTranslation('worlds')
  const [selectedWorld, setSelectedWorld] = useState<string | null>(null)
  const [selectedBranch, setSelectedBranch] = useState<string | null>(null)

  const { data: worlds, isLoading: loadingWorlds, error: listError } = useQuery({
    queryKey: ['worlds'],
    queryFn: api.listWorlds,
  })

  const { data: worldData, isLoading: loadingDetail, error: detailError } = useQuery({
    queryKey: ['world', selectedWorld],
    queryFn: () => api.getWorld(selectedWorld!),
    enabled: !!selectedWorld,
  })

  const { data: branches } = useQuery({
    queryKey: ['branches', selectedWorld],
    queryFn: () => api.listBranches(selectedWorld!),
    enabled: !!selectedWorld,
  })

  const branchMeta = branches?.find((b) => b.name === selectedBranch) ?? null

  return (
    <div className="relative min-h-screen">
      <StarfieldBackground />

      <div className="relative z-10 max-w-4xl mx-auto px-6 py-8">
        <div className="flex items-center gap-4 mb-8">
          <h1 className="text-3xl font-bold text-neon-cyan neon-glow-subtle">{t('title.info')}</h1>
        </div>

        {/* World + branch selector */}
        <div className="glass-panel p-4 mb-6 space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-2">{t('label.selectWorld')}</label>
            {loadingWorlds ? (
              <p className="text-gray-500">{t('status.loading')}</p>
            ) : listError ? (
              <p className="text-red-400 text-sm">{t('status.cannotConnect')}</p>
            ) : worlds && worlds.length > 0 ? (
              <select
                value={selectedWorld ?? ''}
                onChange={(e) => { setSelectedWorld(e.target.value || null); setSelectedBranch(null) }}
                className="w-full bg-space-bg border border-space-border rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-neon-cyan transition-colors"
              >
                <option value="">{t('label.pleaseSelect')}</option>
                {worlds.map((w) => <option key={w} value={w}>{w}</option>)}
              </select>
            ) : (
              <p className="text-gray-500">{t('label.noWorldsYet')}</p>
            )}
          </div>

          {selectedWorld && branches && branches.length > 0 && (
            <div>
              <label className="block text-sm text-gray-400 mb-2">{t('label.selectBranch')}</label>
              <select
                value={selectedBranch ?? ''}
                onChange={(e) => setSelectedBranch(e.target.value || null)}
                className="w-full bg-space-bg border border-space-border rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-neon-cyan transition-colors"
              >
                <option value="">{t('label.baseWorld')}</option>
                {branches.map((b) => (
                  <option key={b.name} value={b.name}>
                    {selectedWorld}/{b.name}
                    {b.fork_layer ? t('label.forkedAt', { layer: t(LAYER_LABELS[b.fork_layer] ?? b.fork_layer) }) : ''}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {loadingDetail && (
          <div className="glass-panel p-8 text-center text-gray-400">{t('label.loadingWorldData')}</div>
        )}

        {detailError && (
          <div className="glass-panel p-6 border-red-500/30">
            <p className="text-red-400">{t('status.loadError')}: {detailError.message}</p>
          </div>
        )}

        {worldData && !loadingDetail && (
          <div className="space-y-6">
            {/* Layer DAG (shared component — also used by WorldDetail overview tab) */}
            {worldData.layers && (
              <LayerDag
                layers={worldData.layers}
                forkLayer={branchMeta?.fork_layer ?? null}
                note={
                  branchMeta
                    ? t('note.branchFork', { layer: t(LAYER_LABELS[branchMeta.fork_layer] ?? branchMeta.fork_layer) })
                    : t('note.engineOrder')
                }
              />
            )}
          </div>
        )}

        {!selectedWorld && !loadingDetail && (
          <div className="glass-panel p-12 text-center">
            <p className="text-gray-500 text-lg">{t('label.pickWorldToView')}</p>
          </div>
        )}
      </div>
    </div>
  )
}
