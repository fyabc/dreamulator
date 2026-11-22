/**
 * CivMapEditorPage — full-page civilization map editor with Leaflet.
 *
 * Route: /worlds/:worldName/civmap/:branchName
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import AtlasIcon from '../components/AtlasIcon'
import WorldContext from '../components/world/WorldContext'
import { useWorldScope } from '../components/world/useWorldScope'
import CivLeafletMap from '../components/civmap/CivLeafletMap'
import { geoJsonAreaKm2, formatArea } from '../components/civmap/areaUtils'
import type {
  BoundaryLevel,
  CivCountry,
  CivSnapshot,
  CivTerritory,
  CountryProvinceMapping,
  PaintToolMode,
  ProvinceInfo,
  TerritoryAssignment,
} from '../components/civmap/types'
import * as api from '../api/civmapClient'
import { isStaticMode } from '../api/mode'
import { staticApi } from '../api/staticClient'

const EMPTY_COUNTRIES: CivCountry[] = []
const EMPTY_ASSIGNMENTS: TerritoryAssignment[] = []
const MAX_UNDO_EDITS = 50

interface PaintEdit {
  before: TerritoryAssignment[]
  after: TerritoryAssignment[]
}

type AssignmentCommand = { updates: TerritoryAssignment[] } | { undo: PaintEdit }

interface AssignmentWrite {
  world: string
  branch: string | null
  snapshotId: string
  command: AssignmentCommand
}

export default function CivMapEditorPage() {
  const { worldName, branchName } = useParams<{
    worldName: string
    branchName: string
  }>()
  const { t } = useTranslation('civmap')
  const queryClient = useQueryClient()

  const world = worldName || ''
  const branch = branchName || null
  const scope = useWorldScope()
  const staticMode = isStaticMode()
  const editScope = JSON.stringify([world, branch])

  // Local UI state
  const [unlockedScope, setUnlockedScope] = useState<string | null>(null)
  const editingUnlocked = !staticMode && unlockedScope === editScope
  const [requestedLevel, setLevel] = useState<BoundaryLevel>('adm1')
  const [toolMode, setToolMode] = useState<PaintToolMode>('paint')
  const [selectedCountry, setSelectedCountry] = useState<CivCountry | null>(null)
  const [hoveredProvince, setHoveredProvince] = useState<ProvinceInfo | null>(null)
  const [editingCountry, setEditingCountry] = useState<CivCountry | null>(null)
  const [editingSnapshot, setEditingSnapshot] = useState<CivSnapshot | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [showBasemap, setShowBasemap] = useState(false)
  const [basemapFailed, setBasemapFailed] = useState(false)
  const [undoHistory, setUndoHistory] = useState<Record<string, PaintEdit[]>>({})
  const [assignmentMessage, setAssignmentMessage] = useState<string | null>(null)
  const assignmentWrite = useRef(false)
  useEffect(() => {
    setUnlockedScope(null)
    setSelectedCountry(null)
    setEditingCountry(null)
    setEditingSnapshot(null)
    setAssignmentMessage(null)
  }, [editScope])
  const handleBasemapError = useCallback(() => {
    setShowBasemap(false)
    setBasemapFailed(true)
  }, [])

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const territoryQuery = useQuery<CivTerritory>({
    queryKey: ['civmap', 'territory', world, branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivTerritory(world, branch)
        : api.getTerritory(world, branch),
    enabled: !!world,
    retry: false,
  })
  const territory = territoryQuery.data

  const levelsQuery = useQuery({
    queryKey: ['civmap', 'levels', world, branch],
    queryFn: () => staticMode
      ? staticApi.getCivAvailableLevels(world)
      : api.getAvailableLevels(world, branch),
    enabled: !!world,
    retry: false,
  })
  const hasAdm1 = levelsQuery.data?.includes('adm1') ?? false
  const hasAdm0 = levelsQuery.data?.includes('adm0') ?? false

  // Always load ADM1 (the fill layer) regardless of current level
  const adm1Query = useQuery({
    queryKey: ['civmap', 'boundaries', world, 'adm1', branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivBoundaries(world, 'adm1')
        : api.getBoundaries(world, 'adm1', branch),
    enabled: hasAdm1,
    retry: false,
  })
  const adm1Geojson = adm1Query.data

  const wantsAdm0 = requestedLevel === 'adm0' && hasAdm0 && !!adm1Geojson?.features.length
  const adm0Query = useQuery({
    queryKey: ['civmap', 'boundaries', world, 'adm0', branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivBoundaries(world, 'adm0')
        : api.getBoundaries(world, 'adm0', branch),
    enabled: wantsAdm0,
    retry: false,
  })
  const adm0Geojson = adm0Query.data

  const mappingQuery = useQuery({
    queryKey: ['civmap', 'mapping', world, branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivMapping(world)
        : api.getCountryProvinceMapping(world, branch),
    enabled: wantsAdm0,
    retry: false,
  })
  const countryProvinceMapRaw = mappingQuery.data

  const countryProvinceMap = useMemo<CountryProvinceMapping>(() => countryProvinceMapRaw ?? {}, [countryProvinceMapRaw])
  const canUseAdm0 = !!adm0Geojson?.features.length && Object.keys(countryProvinceMap).length > 0
  const level = canUseAdm0 ? requestedLevel : 'adm1'
  const adm0Unavailable = wantsAdm0 && !canUseAdm0

  // Reverse mapping: province adm1_code → country ISO_A2
  const provinceCountryMap = useMemo(() => {
    const reverse: Record<string, string> = {}
    for (const [isoA2, provinces] of Object.entries(countryProvinceMap)) {
      for (const pid of provinces) {
        reverse[pid] = isoA2
      }
    }
    return reverse
  }, [countryProvinceMap])

  // Derived data
  const countries = territory?.countries ?? EMPTY_COUNTRIES
  const activeSnapshotId: string | null = territory?.active_snapshot || null
  const historyKey = JSON.stringify([world, branch, activeSnapshotId])
  const currentHistory = undoHistory[historyKey]
  const lastEdit = currentHistory?.[currentHistory.length - 1]
  const assignments: TerritoryAssignment[] =
    activeSnapshotId && territory?.assignments[activeSnapshotId]
      ? territory.assignments[activeSnapshotId]
      : EMPTY_ASSIGNMENTS

  // Auto-select first country if none selected
  useEffect(() => {
    if (!selectedCountry && countries.length > 0) {
      setSelectedCountry(countries[0])
    }
  }, [countries, selectedCountry])

  // Keep selectedCountry in sync with data (e.g. after edit)
  useEffect(() => {
    if (selectedCountry) {
      const updated = countries.find((c) => c.id === selectedCountry.id)
      if (updated && (updated.name !== selectedCountry.name || updated.color !== selectedCountry.color)) {
        setSelectedCountry(updated)
      }
    }
  }, [countries, selectedCountry])

  // ---------------------------------------------------------------------------
  // Mutations
  // ---------------------------------------------------------------------------

  const { mutate: writeAssignments, isPending: assignmentsPending } = useMutation({
    mutationFn: async ({ world, branch, command, snapshotId }: AssignmentWrite) => {
      const current = await api.getTerritory(world, branch)
      const ownerByProvince = new Map(current.assignments[snapshotId]?.map(({ province_id, country_id }) => [province_id, country_id]))
      const ownerOf = (provinceId: string) => ownerByProvince.get(provinceId) ?? ''
      const countryIds = new Set(current.countries.map(country => country.id))
      const snapshotExists = current.snapshots.some(snapshot => snapshot.id === snapshotId)

      if ('undo' in command) {
        if (!snapshotExists
          || command.undo.after.some(({ province_id, country_id }) => ownerOf(province_id) !== country_id)
          || command.undo.before.some(({ country_id }) => country_id !== '' && !countryIds.has(country_id))) {
          return { territory: current, conflict: true }
        }
        const updated = await api.patchAssignments(world, snapshotId, command.undo.before, branch)
        return { territory: updated, undone: true }
      }

      if (!snapshotExists || command.updates.some(({ country_id }) => country_id !== '' && !countryIds.has(country_id))) {
        return { territory: current, conflict: true }
      }
      const after = command.updates.filter(({ province_id, country_id }) => ownerOf(province_id) !== country_id)
      if (!after.length) return { territory: current }
      const before = after.map(({ province_id }) => ({ province_id, country_id: ownerOf(province_id) }))
      const updated = await api.patchAssignments(world, snapshotId, after, branch)
      return { territory: updated, edit: { before, after } }
    },
    onSuccess: async (result, { world, branch, snapshotId, command }) => {
      const queryKey = ['civmap', 'territory', world, branch]
      await queryClient.cancelQueries({ queryKey, exact: true })
      queryClient.setQueryData(queryKey, result.territory)
      if (result.conflict) {
        setAssignmentMessage('undo' in command ? 'mapState.undoConflict' : 'mapState.paintConflict')
        return
      }
      if (!result.edit && !result.undone) return
      const scope = JSON.stringify([world, branch, snapshotId])
      setUndoHistory(history => {
        const edits = history[scope] ?? []
        return { ...history, [scope]: result.edit ? [...edits, result.edit].slice(-MAX_UNDO_EDITS) : edits.slice(0, -1) }
      })
      if (result.undone) setAssignmentMessage('mapState.undone')
    },
    onError: () => setAssignmentMessage('mapState.assignmentSaveFailed'),
    onSettled: () => { assignmentWrite.current = false },
  })

  const createSnapshotMutation = useMutation({
    mutationFn: (snapshot: { id: string; year: number | null; description: string }) => {
      if (staticMode) return Promise.resolve(territory!)
      return api.createSnapshot(world, snapshot, branch)
    },
    onSuccess: (newTerritory) => {
      queryClient.setQueryData(['civmap', 'territory', world, branch], newTerritory)
    },
  })

  const updateSnapshotMutation = useMutation({
    mutationFn: ({ snapshotId, snapshot }: { snapshotId: string; snapshot: CivSnapshot }) => {
      if (staticMode) return Promise.resolve(territory!)
      return api.updateSnapshot(world, snapshotId, snapshot, branch)
    },
    onSuccess: (newTerritory) => {
      queryClient.setQueryData(['civmap', 'territory', world, branch], newTerritory)
      setEditingSnapshot(null)
    },
  })

  const upsertCountryMutation = useMutation({
    mutationFn: (country: CivCountry) => {
      if (staticMode) return Promise.resolve(territory!)
      return api.upsertCountry(world, country, branch)
    },
    onSuccess: (newTerritory) => {
      queryClient.setQueryData(['civmap', 'territory', world, branch], newTerritory)
    },
  })

  const deleteCountryMutation = useMutation({
    mutationFn: (countryId: string) => api.deleteCountry(world, countryId, branch),
    onSuccess: (newTerritory) => {
      queryClient.setQueryData(['civmap', 'territory', world, branch], newTerritory)
      setSelectedCountry(null)
      setEditingCountry(null)
    },
  })

  const otherEditPending = createSnapshotMutation.isPending || updateSnapshotMutation.isPending
    || upsertCountryMutation.isPending || deleteCountryMutation.isPending
  const editPending = assignmentsPending || otherEditPending

  const applyAssignmentCommand = useCallback((command: AssignmentCommand) => {
    if (!editingUnlocked || !activeSnapshotId || otherEditPending || assignmentWrite.current) return
    assignmentWrite.current = true
    setAssignmentMessage(null)
    writeAssignments({ world, branch, command, snapshotId: activeSnapshotId })
  }, [world, branch, editingUnlocked, activeSnapshotId, otherEditPending, writeAssignments])

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  /**
   * Level-aware paint handler.
   * Always receives a province adm1_code (from the ADM1 fill layer).
   * At ADM0 level: expands to all provinces of the clicked province's country.
   * At ADM1 level: paints a single province.
   */
  const handleProvincePaint = useCallback(
    (provinceId: string) => {
      if (adm0Unavailable || !provinceId || toolMode === 'select' || (toolMode === 'paint' && !selectedCountry)) return

      let provinceIds: string[]
      if (level === 'adm0') {
        // Find the country this province belongs to, expand to all its provinces
        const isoA2 = provinceCountryMap[provinceId]
        if (!isoA2) {
          provinceIds = [provinceId]
        } else {
          provinceIds = countryProvinceMap[isoA2] || [provinceId]
        }
      } else {
        provinceIds = [provinceId]
      }

      const countryId = toolMode === 'paint' ? selectedCountry?.id ?? '' : ''
      applyAssignmentCommand({ updates: provinceIds.map(id => ({ province_id: id, country_id: countryId })) })
    },
    [adm0Unavailable, level, provinceCountryMap, countryProvinceMap, toolMode, selectedCountry, applyAssignmentCommand],
  )

  const handleProvinceHover = useCallback((info: ProvinceInfo | null) => {
    setHoveredProvince(info)
  }, [])

  const handleAddCountry = useCallback(() => {
    const id = `civ_${Date.now().toString(36)}`
    const colors = ['#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#8B4513']
    const color = colors[countries.length % colors.length]
    upsertCountryMutation.mutate({
      id,
      name: t('action.newCountry'),
      color,
      description: '',
    })
  }, [countries.length, upsertCountryMutation])

  const handleCreateSnapshot = useCallback(() => {
    const id = `snap_${Date.now().toString(36)}`
    createSnapshotMutation.mutate({ id, year: null, description: t('action.newSnapshot') })
  }, [createSnapshotMutation])

  const handleSaveCountryEdit = useCallback(() => {
    if (editingCountry) {
      upsertCountryMutation.mutate(editingCountry)
      setEditingCountry(null)
    }
  }, [editingCountry, upsertCountryMutation])

  // Calculate area (km²) per fictional country from assigned provinces
  const areaCounts = useMemo(() => {
    const areas = new Map<string, number>()
    if (!adm1Geojson?.features) return areas
    const featureMap = new Map<string, any>()
    for (const f of adm1Geojson.features) {
      if (f.id) featureMap.set(f.id as string, f)
    }
    for (const a of assignments) {
      const feature = featureMap.get(a.province_id)
      if (feature?.geometry) {
        const area = geoJsonAreaKm2(feature.geometry)
        areas.set(a.country_id, (areas.get(a.country_id) || 0) + area)
      }
    }
    return areas
  }, [assignments, adm1Geojson])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const loading = levelsQuery.isLoading || adm1Query.isLoading || territoryQuery.isLoading
  const loadFailed = levelsQuery.isError || adm1Query.isError || territoryQuery.isError
  const hasBoundaries = !!adm1Geojson?.features.length
  const mapReady = !loading && !loadFailed && hasBoundaries
  const canEdit = editingUnlocked && territoryQuery.isSuccess
  const canUndo = canEdit && !!lastEdit && !editPending && !editingCountry && !editingSnapshot
  const handleUndo = useCallback(() => {
    if (canUndo && lastEdit) applyAssignmentCommand({ undo: lastEdit })
  }, [canUndo, lastEdit, applyAssignmentCommand])

  useLayoutEffect(() => {
    if (!canUndo) return
    const undoShortcut = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || event.repeat || event.altKey || event.shiftKey
        || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z') return
      const target = event.target
      if (target instanceof HTMLElement && (target.isContentEditable || target.closest('input, textarea, select'))) return
      event.preventDefault()
      handleUndo()
    }
    window.addEventListener('keydown', undoShortcut)
    return () => window.removeEventListener('keydown', undoShortcut)
  }, [canUndo, handleUndo])

  const activeTool = mapReady && canEdit && activeSnapshotId && !adm0Unavailable ? toolMode : 'select'
  const assignmentStatus = assignmentsPending ? 'mapState.savingAssignments' : assignmentMessage
  const worldPath = `/worlds/${encodeURIComponent(world)}?${new URLSearchParams({ ...(branch ? { branch } : {}), tab: 'civilization' })}`
  const actionClass = 'inline-flex min-h-10 items-center gap-1.5 rounded-md border border-space-border bg-space-panel px-2.5 text-xs text-slate-200 hover:text-white disabled:opacity-50'

  const toggleEditing = () => {
    if (editPending || assignmentWrite.current) return
    setUnlockedScope(editingUnlocked ? null : editScope)
    setEditingCountry(null)
    setEditingSnapshot(null)
    setAssignmentMessage(null)
    if (!editingUnlocked) setToolMode('paint')
  }

  const retryMap = () => {
    void levelsQuery.refetch()
    if (hasAdm1) void adm1Query.refetch()
    if (territoryQuery.isError) void territoryQuery.refetch()
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-space-bg text-slate-100">
      {/* Top bar */}
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-space-border bg-space-panel px-3 py-2 sm:px-4">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Link to={worldPath} className={actionClass} aria-label={t('action.backToWorld')} title={t('action.backToWorld')}>
            <AtlasIcon name="back" />
          </Link>
          <div className="min-w-0">
            <h1 className="truncate text-base font-semibold sm:text-lg">{t('title.editorTitle')}</h1>
            {scope && <WorldContext scope={scope} />}
          </div>
          {!staticMode && <button type="button" role="switch" aria-checked={!editingUnlocked} aria-label={t('action.lockEditing')}
            className={`${actionClass} ml-auto shrink-0 ${editingUnlocked ? 'border-neon-cyan/40 text-neon-cyan' : ''}`}
            disabled={editPending} onClick={toggleEditing} title={t(editingUnlocked ? 'hint.lockEditing' : 'hint.unlockEditing')}>
            <AtlasIcon name={editingUnlocked ? 'unlock' : 'lock'} className="size-4" />
            {t(editingUnlocked ? 'title.editing' : 'title.editLocked')}
          </button>}
          <button
            type="button"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className={`${actionClass} shrink-0 lg:hidden ${staticMode ? 'ml-auto' : ''}`}
            aria-label={t('title.toolbar')}
            aria-expanded={sidebarOpen}
            aria-controls="civmap-tools"
          >
            <AtlasIcon name="menu" />
          </button>
        </div>

        {/* Level selector */}
        <div className="ml-auto flex w-full flex-wrap items-center gap-2 sm:w-auto">
          {editingUnlocked && <button type="button" className={actionClass} disabled={!canUndo} onClick={handleUndo}
            aria-keyshortcuts="Control+Z Meta+Z" title={t('hint.undo')}>
            <AtlasIcon name="undo" className="size-4" />{t('action.undo')}
          </button>}
          {mapReady && (
            <>
              <label className="flex items-center gap-2 text-xs text-slate-400">
                {t('label.level')}
                <select value={hasAdm0 ? requestedLevel : 'adm1'} onChange={(event) => setLevel(event.target.value as BoundaryLevel)} className={actionClass}>
                  <option value="adm1">{t('level.adm1')}</option>
                  {hasAdm0 && <option value="adm0">{t('level.adm0')}</option>}
                </select>
              </label>
              <button type="button" className={actionClass} aria-pressed={showBasemap} onClick={() => {
                setBasemapFailed(false)
                setShowBasemap(!showBasemap)
              }}>
                <AtlasIcon name="layers" className="size-4" />{t('action.basemap')}
                <span className="text-slate-400">{t(showBasemap ? 'label.on' : 'label.off')}</span>
              </button>
            </>
          )}
          <Link to="/help#civmap" target="_blank" rel="noreferrer" className={actionClass}>
            <AtlasIcon name="help" className="size-4" />{t('action.help')}
          </Link>
        </div>
      </header>

      {/* Main content: 3-panel layout */}
      <div className="flex flex-1 min-h-0 relative">
        {/* Mobile sidebar backdrop */}
        {sidebarOpen && (
          <div
            className="lg:hidden fixed inset-0 bg-black/50 z-40"
            onClick={() => setSidebarOpen(false)}
          />
        )}

        {/* Left panel: Country palette + tools — drawer on mobile, fixed on desktop */}
        <aside id="civmap-tools" className={`
          fixed lg:static inset-y-0 left-0 z-50 lg:z-auto
          w-64 bg-space-panel border-r border-space-border flex flex-col overflow-y-auto shrink-0
          transition-transform duration-200 ease-in-out
          ${sidebarOpen ? 'translate-x-0' : 'invisible -translate-x-full lg:visible lg:translate-x-0'}
        `}>
          {/* Mobile close button */}
          <div className="lg:hidden flex justify-end p-2 border-b border-gray-700">
            <button
              onClick={() => setSidebarOpen(false)}
              className={actionClass}
              aria-label={t('action.closeTools')}
            >
              <AtlasIcon name="close" />
            </button>
          </div>
          {/* Tools */}
          {editingUnlocked && <div className="p-3 border-b border-space-border">
            <h2 className="text-xs uppercase text-gray-500 mb-2">{t('panel.tools')}</h2>
            <div className="flex gap-1">
              {([
                ['paint', t('tool.paint')],
                ['erase', t('tool.erase')],
                ['select', t('tool.select')],
              ] as const).map(([mode, label]) => (
                <button
                  key={mode}
                  aria-pressed={activeTool === mode}
                  disabled={mode !== 'select' && (!mapReady || !canEdit || !activeSnapshotId || adm0Unavailable || (mode === 'paint' && !selectedCountry))}
                  onClick={() => setToolMode(mode)}
                  className={`flex-1 text-xs py-1.5 rounded disabled:opacity-50 ${
                    activeTool === mode
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>}

          {/* Country palette */}
          <div className="p-3 flex-1">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xs uppercase text-gray-500">{t('panel.countries')}</h2>
              {editingUnlocked && (
                <button
                  onClick={handleAddCountry}
                  disabled={!canEdit || editPending}
                  className="text-xs text-blue-400 hover:text-blue-300"
                >
                  {t('action.add')}
                </button>
              )}
            </div>

            {territoryQuery.isSuccess && countries.length === 0 && (
              <p className="text-xs text-gray-500">
                {t(editingUnlocked ? 'hint.addCountry' : 'hint.noCountries')}
              </p>
            )}

            <div className="space-y-1">
              {countries.map((c) => (
                <div
                  key={c.id}
                  className={`flex items-center gap-2 px-2 py-1.5 rounded text-sm ${
                    selectedCountry?.id === c.id
                      ? 'bg-gray-600 ring-1 ring-blue-400'
                      : 'hover:bg-gray-700'
                  }`}
                >
                  <button
                    onClick={() => setSelectedCountry(c)}
                    className="flex items-center gap-2 flex-1 min-w-0 text-left"
                  >
                    <span
                      className="w-4 h-4 rounded shrink-0"
                      style={{ backgroundColor: c.color }}
                    />
                    <span className="truncate">{c.name}</span>
                    <span className="text-xs text-gray-500 shrink-0">
                      {(areaCounts.get(c.id) ?? 0) > 0 ? `${formatArea(areaCounts.get(c.id)!)} km²` : ''}
                    </span>
                  </button>
                  {editingUnlocked && <button
                    disabled={!canEdit || editPending}
                    onClick={() => setEditingCountry({ ...c })}
                    className="shrink-0 text-xs text-slate-400 hover:text-white"
                  >
                    {t('action.edit')}
                  </button>}
                </div>
              ))}
            </div>
          </div>

          {/* Snapshot section */}
          <div className="p-3 border-t border-gray-700">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xs uppercase text-gray-500">{t('panel.snapshots')}</h2>
              {editingUnlocked && (
                <button
                  onClick={handleCreateSnapshot}
                  disabled={!canEdit || editPending}
                  className="text-xs text-blue-400 hover:text-blue-300"
                >
                  {t('action.add')}
                </button>
              )}
            </div>

            {territoryQuery.isSuccess && territoryQuery.data.snapshots.length === 0 && (
              <p className="text-xs text-gray-500">
                {t(editingUnlocked ? 'hint.addSnapshot' : 'hint.noSnapshots')}
              </p>
            )}

            <div className="space-y-1">
              {territory?.snapshots.map((s) => (
                <div
                  key={s.id}
                  className={`flex items-center text-xs px-2 py-1 rounded cursor-pointer ${
                    s.id === activeSnapshotId
                      ? 'bg-blue-900/50 text-blue-300'
                      : 'text-gray-400 hover:bg-gray-700'
                  }`}
                >
                  <span className="flex-1 truncate">
                    {s.year ? `${s.year}${t('label.yearSuffix')}` : s.id} — {s.description || t('label.noDescription')}
                  </span>
                  {editingUnlocked && <button
                    disabled={!canEdit || editPending}
                    onClick={(e) => {
                      e.stopPropagation()
                      setEditingSnapshot({ ...s })
                    }}
                    className="ml-1 shrink-0 text-slate-400 hover:text-white"
                  >
                    {t('action.edit')}
                  </button>}
                </div>
              ))}
            </div>
          </div>
        </aside>

        {/* Center: Map */}
        <main className="relative min-w-0 flex-1 isolate">
          {mapReady ? <CivLeafletMap
            adm1Geojson={adm1Geojson || null}
            adm0Geojson={adm0Geojson || null}
            level={level}
            countries={countries}
            assignments={assignments}
            provinceCountryMap={provinceCountryMap}
            countryProvinceMap={countryProvinceMap}
            toolMode={activeTool}
            onProvinceHover={handleProvinceHover}
            onProvincePaint={activeTool === 'select' ? undefined : handleProvincePaint}
            showBasemap={showBasemap}
            onBasemapError={handleBasemapError}
          /> : (
            <div className="grid h-full place-items-center overflow-auto p-4">
              <section className="w-full max-w-md rounded-xl border border-space-border bg-space-panel p-5" role={loadFailed ? 'alert' : 'status'}>
                <h2 className="font-semibold text-slate-100">{t(loading ? 'label.loadingMap' : loadFailed ? 'mapState.loadFailed' : 'mapState.missing')}</h2>
                {!loading && (
                  <>
                    <p className="mt-2 text-sm leading-relaxed text-slate-300">{t(loadFailed ? 'mapState.loadFailedDetail' : staticMode ? 'mapState.missingStatic' : 'mapState.missingLive')}</p>
                    {(!staticMode || loadFailed) && (
                      <button type="button" className={`${actionClass} mt-4`} onClick={retryMap} disabled={levelsQuery.isFetching || adm1Query.isFetching || territoryQuery.isFetching}>{t('action.retry')}</button>
                    )}
                  </>
                )}
              </section>
            </div>
          )}
          {!staticMode && <div role="status" className="pointer-events-none absolute inset-x-3 bottom-6 z-[1000] flex justify-center">
            {assignmentStatus && <p className="rounded-md border border-space-border bg-space-panel px-3 py-2 text-xs text-slate-200">
              {t(assignmentStatus)}
            </p>}
          </div>}
          {adm0Unavailable && <div className="absolute inset-x-14 top-2 z-[1000] mx-auto flex max-w-sm flex-wrap items-center gap-2 rounded-md border border-space-border bg-space-panel px-3 py-2 text-xs text-slate-200">
            <span role="status">{t(adm0Query.isFetching || mappingQuery.isFetching ? 'mapState.loadingAdm0' : 'mapState.adm0Unavailable')}</span>
            {!adm0Query.isFetching && !mappingQuery.isFetching && <button type="button" className="text-neon-cyan underline" onClick={() => {
              void adm0Query.refetch()
              void mappingQuery.refetch()
            }}>{t('action.retry')}</button>}
          </div>}
          {mapReady && basemapFailed && (
            <p role="status" className="absolute inset-x-12 top-2 z-[1000] mx-auto max-w-sm rounded-md border border-space-border bg-space-panel px-3 py-2 text-xs text-slate-200">
              {t('mapState.basemapFailed')}
            </p>
          )}
        </main>

        {/* Right panel: Province inspector — hidden on mobile */}
        <aside className="hidden w-56 shrink-0 overflow-y-auto border-l border-space-border bg-space-panel p-3 lg:block">
          <h2 className="text-xs uppercase text-gray-500 mb-2">
            {level === 'adm0' ? t('panel.countryInfo') : t('panel.provinceInfo')}
          </h2>

          {hoveredProvince ? (
            <div className="space-y-2">
              <div>
                <div className="text-sm font-medium">{hoveredProvince.name}</div>
                <div className="text-xs text-gray-400">
                  {hoveredProvince.admin} · {hoveredProvince.type}
                </div>
              </div>

              <div className="text-xs">
                <span className="text-gray-500">ID: </span>
                <span className="text-gray-300 font-mono">{hoveredProvince.id}</span>
              </div>

              {/* ADM0: show province breakdown */}
              {level === 'adm0' && hoveredProvince.province_count != null && (
                <div className="text-xs text-gray-400">
                  {t('panel.paintedCount', { painted: hoveredProvince.painted_count, total: hoveredProvince.province_count })}
                </div>
              )}

              {hoveredProvince.country_name && (
                <div className="flex items-center gap-2 mt-2 pt-2 border-t border-gray-700">
                  <span
                    className="w-3 h-3 rounded"
                    style={{ backgroundColor: hoveredProvince.country_color || '#666' }}
                  />
                  <span className="text-sm">{hoveredProvince.country_name}</span>
                </div>
              )}

              {!hoveredProvince.country_name && (
                <div className="text-xs text-gray-500 mt-2 pt-2 border-t border-gray-700">
                  {t('panel.unassigned')}
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-gray-500">
              {t('panel.hoverHint')}{level === 'adm0' ? t('panel.hoverHintCountry') : t('panel.hoverHintProvince')}{t('panel.hoverHintSuffix')}
            </p>
          )}

          {/* Stats */}
          <div className="mt-6 pt-4 border-t border-gray-700">
            <h2 className="text-xs uppercase text-gray-500 mb-2">{t('panel.stats')}</h2>
            <div className="space-y-1 text-xs text-gray-400">
              <div>{t('stats.countries', { count: countries.length })}</div>
              <div>{t('stats.assignedProvinces', { count: assignments.length })}</div>
              <div>
                {t('stats.snapshots', { count: territory?.snapshots.length || 0 })}
              </div>
            </div>
          </div>

          {/* No snapshot warning */}
          {canEdit && mapReady && !activeSnapshotId && (
            <div className="mt-4 p-2 bg-yellow-900/30 border border-yellow-700/50 rounded text-xs text-yellow-300">
              {t('hint.createSnapshotFirst')}
            </div>
          )}
        </aside>
      </div>

      {/* Status bar */}
      <footer className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-t border-space-border bg-space-panel px-3 py-2 text-xs text-slate-300 sm:px-4">
        {/* Mobile: show hovered province info (right panel hidden) */}
        {hoveredProvince && (
          <span className="lg:hidden truncate">
            {hoveredProvince.name}
            {hoveredProvince.country_name && (
              <span className="ml-1" style={{ color: hoveredProvince.country_color || undefined }}>
                · {hoveredProvince.country_name}
              </span>
            )}
          </span>
        )}
        <span className={hoveredProvince ? 'hidden lg:inline' : ''}>
          {staticMode ? t('title.readonly') : !editingUnlocked ? t('title.browsing') : activeTool === 'paint' && selectedCountry
            ? t('status.painting', { name: selectedCountry.name })
            : activeTool === 'erase'
              ? t('status.erasing')
              : t('status.selecting')}
        </span>
        {activeSnapshotId && (
          <span>{t('status.currentSnapshot', { id: activeSnapshotId })}</span>
        )}
        <span className="ml-auto">
          {mapReady ? t('panel.provinceCount', { count: adm1Geojson.features.length }) : t(loading ? 'label.loading' : 'mapState.unavailable')}
          {level === 'adm0' && adm0Geojson ? ` · ${adm0Geojson.features.length} ${t('level.adm0')}` : ''}
        </span>
      </footer>

      {/* Snapshot edit modal */}
      {canEdit && editingSnapshot && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[2000]">
          <div className="bg-gray-800 rounded-lg p-6 w-80 shadow-xl border border-gray-600">
            <h3 className="text-lg font-semibold mb-4">{t('dialog.editSnapshotTitle')}</h3>

            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">{t('label.year')}</label>
                <input
                  type="number"
                  value={editingSnapshot.year ?? ''}
                  onChange={(e) =>
                    setEditingSnapshot({
                      ...editingSnapshot,
                      year: e.target.value ? parseInt(e.target.value, 10) : null,
                    })
                  }
                  placeholder={t('label.optional')}
                  className="w-full bg-gray-700 text-white rounded px-3 py-1.5 text-sm border border-gray-600 focus:border-blue-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">{t('label.description')}</label>
                <input
                  type="text"
                  value={editingSnapshot.description}
                  onChange={(e) =>
                    setEditingSnapshot({ ...editingSnapshot, description: e.target.value })
                  }
                  className="w-full bg-gray-700 text-white rounded px-3 py-1.5 text-sm border border-gray-600 focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 mt-5">
              <button
                onClick={() => setEditingSnapshot(null)}
                className="px-3 py-1.5 text-sm text-gray-300 bg-gray-700 rounded hover:bg-gray-600"
              >
                {t('action.cancel')}
              </button>
              <button
                onClick={() =>
                  updateSnapshotMutation.mutate({
                    snapshotId: editingSnapshot.id,
                    snapshot: editingSnapshot,
                  })
                }
                className="px-3 py-1.5 text-sm text-white bg-blue-600 rounded hover:bg-blue-500"
              >
                {t('action.save')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Country edit modal */}
      {canEdit && editingCountry && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[2000]">
          <div className="bg-gray-800 rounded-lg p-6 w-80 shadow-xl border border-gray-600">
            <h3 className="text-lg font-semibold mb-4">{t('dialog.editCountryTitle')}</h3>

            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">{t('label.name')}</label>
                <input
                  type="text"
                  value={editingCountry.name}
                  onChange={(e) =>
                    setEditingCountry({ ...editingCountry, name: e.target.value })
                  }
                  className="w-full bg-gray-700 text-white rounded px-3 py-1.5 text-sm border border-gray-600 focus:border-blue-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">{t('label.color')}</label>
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    value={editingCountry.color}
                    onChange={(e) =>
                      setEditingCountry({ ...editingCountry, color: e.target.value })
                    }
                    className="w-10 h-8 rounded cursor-pointer bg-transparent border-0"
                  />
                  <input
                    type="text"
                    value={editingCountry.color}
                    onChange={(e) =>
                      setEditingCountry({ ...editingCountry, color: e.target.value })
                    }
                    className="flex-1 bg-gray-700 text-white rounded px-3 py-1.5 text-sm font-mono border border-gray-600 focus:border-blue-500 focus:outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">{t('label.description')}</label>
                <textarea
                  value={editingCountry.description}
                  onChange={(e) =>
                    setEditingCountry({ ...editingCountry, description: e.target.value })
                  }
                  rows={2}
                  className="w-full bg-gray-700 text-white rounded px-3 py-1.5 text-sm border border-gray-600 focus:border-blue-500 focus:outline-none resize-none"
                />
              </div>
            </div>

            <div className="flex justify-between mt-5">
              <button
                onClick={() => {
                  if (confirm(t('action.deleteConfirm'))) {
                    deleteCountryMutation.mutate(editingCountry.id)
                  }
                }}
                className="text-sm text-red-400 hover:text-red-300"
              >
                {t('action.deleteCountry')}
              </button>
              <div className="flex gap-2">
                <button
                  onClick={() => setEditingCountry(null)}
                  className="px-3 py-1.5 text-sm text-gray-300 bg-gray-700 rounded hover:bg-gray-600"
                >
                  {t('action.cancel')}
                </button>
                <button
                  onClick={handleSaveCountryEdit}
                  className="px-3 py-1.5 text-sm text-white bg-blue-600 rounded hover:bg-blue-500"
                >
                  {t('action.save')}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
