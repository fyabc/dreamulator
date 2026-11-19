/**
 * ImportPage — the first journey for authors who already have a heightmap.
 *
 * Route: /import (API mode only).  The author picks where the map goes (a new
 * world from a template, or an existing world's geological layer), declares
 * the mapping, checks the backend preview and confirms.  Nothing is written
 * before the confirm button; a new world is created only then, and removed
 * again if the import itself fails, so a failed attempt leaves no half world.
 */

import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { isStaticMode } from '../api/mode'
import {
  WORLD_NAME_PATTERN,
  suggestWorldName,
  type ElevationImportResponse,
  type ElevationImportTarget,
  type ElevationMapping,
  type ImportedState,
} from '../api/elevationImport'
import ElevationImportPanel from '../components/import/ElevationImportPanel'
import { saveLastWorld } from '../utils/lastWorld'

/** Layers a branch may fork at and still own the geological input. */
const GEOLOGICAL_OWNERS = new Set(['physics', 'chemistry', 'astronomy', 'geological'])
const TEMPLATES = ['earthlike', 'minimal'] as const

export default function ImportPage() {
  const { t } = useTranslation('importer')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const staticMode = isStaticMode()

  const [targetKind, setTargetKind] = useState<'new' | 'existing'>('new')
  const [worldName, setWorldName] = useState('')
  const [nameTouched, setNameTouched] = useState(false)
  const [template, setTemplate] = useState<(typeof TEMPLATES)[number]>('earthlike')
  const [existingWorld, setExistingWorld] = useState('')
  const [existingPlanet, setExistingPlanet] = useState('')
  const [existingBranch, setExistingBranch] = useState('')

  const { data: worlds } = useQuery({ queryKey: ['worlds'], queryFn: api.listWorlds, enabled: !staticMode })
  const { data: worldInfo } = useQuery({
    queryKey: ['world', existingWorld],
    queryFn: () => api.getWorld(existingWorld),
    enabled: !staticMode && targetKind === 'existing' && !!existingWorld,
  })
  const { data: branches } = useQuery({
    queryKey: ['branches', existingWorld],
    queryFn: () => api.listBranches(existingWorld),
    enabled: !staticMode && targetKind === 'existing' && !!existingWorld,
  })
  const planetIds: string[] = useMemo(() => worldInfo?.planet_ids ?? [], [worldInfo])
  const planet = existingPlanet || planetIds[0] || ''
  const geoBranches = useMemo(
    () => (branches ?? []).filter((b: { fork_layer?: string | null }) => b.fork_layer && GEOLOGICAL_OWNERS.has(b.fork_layer)),
    [branches],
  )

  const target: ElevationImportTarget | null =
    targetKind === 'existing' && existingWorld && planet
      ? { world: existingWorld, planetId: planet, branch: existingBranch || null }
      : null

  const nameError = (() => {
    if (targetKind !== 'new') return null
    if (!worldName) return t('target.nameRequired')
    if (!WORLD_NAME_PATTERN.test(worldName)) return t('target.nameInvalid')
    if (worlds?.includes(worldName)) return t('target.nameTaken', { name: worldName })
    return null
  })()
  const blocked =
    targetKind === 'new' ? nameError : !existingWorld ? t('target.pickWorld') : !planet ? t('target.noPlanet') : null

  if (staticMode) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-16 text-center text-gray-400">
        <p>{t('static.unavailable')}</p>
        <Link to="/worlds" className="text-neon-cyan hover:underline">{t('static.browse')}</Link>
      </div>
    )
  }

  const confirm = async (file: File, mapping: ElevationMapping, notes: string): Promise<ElevationImportResponse> => {
    let world: string
    let planetId: string
    let branch: string | null = null
    let created = false
    if (targetKind === 'new') {
      world = worldName
      const info = await api.createWorld(world, template)
      created = true
      planetId = info?.planet_ids?.[0]
      if (!planetId) {
        await api.deleteWorld(world).catch(() => undefined)
        throw new Error(t('error.templateNoPlanet', { template }))
      }
    } else {
      world = existingWorld
      planetId = planet
      branch = existingBranch || null
    }
    let result: ElevationImportResponse
    try {
      result = await api.importElevation(world, planetId, file, branch, mapping, notes || undefined)
    } catch (e) {
      if (created) await api.deleteWorld(world).catch(() => undefined)
      throw e
    }
    await queryClient.invalidateQueries({ queryKey: ['worlds'] })
    for (const key of ['elevationBlob', 'voronoi', 'cvtMesh', 'plates', 'mapMeta', 'mapPlanets']) {
      await queryClient.invalidateQueries({ queryKey: [key, world] })
    }
    const qs = branch ? `?branch=${encodeURIComponent(branch)}` : ''
    const path = `/worlds/${encodeURIComponent(world)}/map/${encodeURIComponent(planetId)}${qs}`
    saveLastWorld({ world, planetId, branch, path })
    const state: ImportedState = { imported: { world, created, result } }
    navigate(path, { state })
    return result
  }

  return (
    <div className="max-w-6xl mx-auto px-4 md:px-6 py-8 space-y-5">
      <div>
        <Link to="/" className="text-sm text-gray-400 hover:text-neon-cyan">{t('action.backHome')}</Link>
        <h1 className="text-2xl font-bold text-neon-cyan neon-glow-subtle mt-2">{t('title')}</h1>
        <p className="text-sm text-gray-400 mt-1 max-w-3xl">{t('intro')}</p>
      </div>

      <section className="glass-panel p-4 space-y-3">
        <h2 className="text-sm font-semibold text-gray-200">{t('step.target')}</h2>
        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-2 text-gray-200">
            <input type="radio" checked={targetKind === 'new'} onChange={() => setTargetKind('new')} data-testid="target-new" />
            {t('target.new')}
          </label>
          <label className="flex items-center gap-2 text-gray-200">
            <input type="radio" checked={targetKind === 'existing'} onChange={() => setTargetKind('existing')} data-testid="target-existing" />
            {t('target.existing')}
          </label>
        </div>
        {targetKind === 'new' ? (
          <p className="text-xs text-gray-400">{t('target.newHelp')}</p>
        ) : (
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="text-gray-300">
              {t('target.world')}
              <select
                className="ml-2 bg-space-surface border border-space-border rounded px-2 py-1"
                value={existingWorld}
                data-testid="existing-world"
                onChange={(e) => {
                  setExistingWorld(e.target.value)
                  setExistingPlanet('')
                  setExistingBranch('')
                }}
              >
                <option value="">{t('target.pickWorldOption')}</option>
                {(worlds ?? []).map((w) => (
                  <option key={w} value={w}>{w}</option>
                ))}
              </select>
            </label>
            {planetIds.length > 1 && (
              <label className="text-gray-300">
                {t('target.planet')}
                <select className="ml-2 bg-space-surface border border-space-border rounded px-2 py-1" value={planet} onChange={(e) => setExistingPlanet(e.target.value)}>
                  {planetIds.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </label>
            )}
            {existingWorld && (
              <label className="text-gray-300">
                {t('target.branch')}
                <select className="ml-2 bg-space-surface border border-space-border rounded px-2 py-1" value={existingBranch} onChange={(e) => setExistingBranch(e.target.value)}>
                  <option value="">{t('target.rootBranch')}</option>
                  {geoBranches.map((b: { name: string }) => (
                    <option key={b.name} value={b.name}>{b.name}</option>
                  ))}
                </select>
              </label>
            )}
            <p className="w-full text-xs text-gray-400">{t('target.existingHelp')}</p>
          </div>
        )}
      </section>

      <ElevationImportPanel
        target={target}
        onConfirm={confirm}
        onCancel={() => navigate('/')}
        confirmBlockedReason={blocked}
        confirmExtras={
          targetKind === 'new' ? (
            <div className="flex flex-wrap gap-4 items-start text-sm">
              <label className="text-gray-300">
                {t('target.name')}
                <input
                  value={worldName}
                  onChange={(e) => {
                    setWorldName(e.target.value)
                    setNameTouched(true)
                  }}
                  data-testid="world-name"
                  placeholder="my-world"
                  className="ml-2 w-48 bg-space-surface border border-space-border rounded px-2 py-1 text-gray-100"
                />
                <span className="block text-xs text-gray-500 mt-0.5">{t('target.nameHelp')}</span>
              </label>
              <label className="text-gray-300">
                {t('target.template')}
                <select className="ml-2 bg-space-surface border border-space-border rounded px-2 py-1" value={template} onChange={(e) => setTemplate(e.target.value as (typeof TEMPLATES)[number])}>
                  {TEMPLATES.map((tpl) => (
                    <option key={tpl} value={tpl}>{t(`template.${tpl}`)}</option>
                  ))}
                </select>
                <span className="block text-xs text-gray-500 mt-0.5">{t(`template.${template}Help`)}</span>
              </label>
            </div>
          ) : null
        }
        onFileChosen={(name) => {
          if (!nameTouched) setWorldName(suggestWorldName(name, worlds ?? []))
        }}
      />
    </div>
  )
}
