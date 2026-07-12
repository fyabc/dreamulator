/**
 * CivMapEditorPage — full-page civilization map editor with Leaflet.
 *
 * Route: /worlds/:worldName/civmap/:branchName
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import CivLeafletMap from '../components/civmap/CivLeafletMap'
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

export default function CivMapEditorPage() {
  const { worldName, branchName } = useParams<{
    worldName: string
    branchName: string
  }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const world = worldName || ''
  const branch = branchName || null
  const staticMode = isStaticMode()

  // Local UI state
  const [level, setLevel] = useState<BoundaryLevel>('adm1')
  const [toolMode, setToolMode] = useState<PaintToolMode>('paint')
  const [selectedCountry, setSelectedCountry] = useState<CivCountry | null>(null)
  const [hoveredProvince, setHoveredProvince] = useState<ProvinceInfo | null>(null)
  const [editingCountry, setEditingCountry] = useState<CivCountry | null>(null)
  const [editingSnapshot, setEditingSnapshot] = useState<CivSnapshot | null>(null)

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const { data: territory, isLoading: terrLoading } = useQuery<CivTerritory>({
    queryKey: ['civmap', 'territory', world, branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivTerritory(world, branch) as Promise<CivTerritory>
        : api.getTerritory(world, branch),
    enabled: !!world,
  })

  // Always load ADM1 (the fill layer) regardless of current level
  const { data: adm1Geojson, isLoading: adm1Loading } = useQuery({
    queryKey: ['civmap', 'boundaries', world, 'adm1', branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivBoundaries(world, 'adm1')
        : api.getBoundaries(world, 'adm1', branch),
    enabled: !!world,
  })

  // Load ADM0 for border overlay (always loaded for instant switching)
  const { data: adm0Geojson } = useQuery({
    queryKey: ['civmap', 'boundaries', world, 'adm0', branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivBoundaries(world, 'adm0')
        : api.getBoundaries(world, 'adm0', branch),
    enabled: !!world,
  })

  const { data: availableLevels } = useQuery({
    queryKey: ['civmap', 'levels', world, branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivAvailableLevels(world)
        : api.getAvailableLevels(world, branch),
    enabled: !!world,
  })

  // Country→province mapping (always loaded, level-independent)
  const { data: countryProvinceMapRaw } = useQuery({
    queryKey: ['civmap', 'mapping', world, branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivMapping(world)
        : api.getCountryProvinceMapping(world, branch),
    enabled: !!world,
  })

  const countryProvinceMap: CountryProvinceMapping = countryProvinceMapRaw || {}

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
  const countries: CivCountry[] = territory?.countries || []
  const activeSnapshotId: string | null = territory?.active_snapshot || null
  const assignments: TerritoryAssignment[] =
    activeSnapshotId && territory?.assignments[activeSnapshotId]
      ? territory.assignments[activeSnapshotId]
      : []

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

  const patchMutation = useMutation({
    mutationFn: (updates: TerritoryAssignment[]) => {
      if (staticMode) return Promise.resolve(territory!)
      return api.patchAssignments(world, activeSnapshotId!, updates, branch)
    },
    onSuccess: (newTerritory) => {
      queryClient.setQueryData(['civmap', 'territory', world, branch], newTerritory)
    },
  })

  const createSnapshotMutation = useMutation({
    mutationFn: (snapshot: { id: string; year: number | null; description: string }) =>
      api.createSnapshot(world, snapshot, branch),
    onSuccess: (newTerritory) => {
      queryClient.setQueryData(['civmap', 'territory', world, branch], newTerritory)
    },
  })

  const updateSnapshotMutation = useMutation({
    mutationFn: ({ snapshotId, snapshot }: { snapshotId: string; snapshot: CivSnapshot }) =>
      api.updateSnapshot(world, snapshotId, snapshot, branch),
    onSuccess: (newTerritory) => {
      queryClient.setQueryData(['civmap', 'territory', world, branch], newTerritory)
      setEditingSnapshot(null)
    },
  })

  const upsertCountryMutation = useMutation({
    mutationFn: (country: CivCountry) => api.upsertCountry(world, country, branch),
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
      if (staticMode || !activeSnapshotId) return

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

      if (toolMode === 'paint' && selectedCountry) {
        const updates = provinceIds.map((pid) => ({
          province_id: pid,
          country_id: selectedCountry.id,
        }))
        patchMutation.mutate(updates)
      } else if (toolMode === 'erase') {
        const updates = provinceIds.map((pid) => ({
          province_id: pid,
          country_id: '',
        }))
        patchMutation.mutate(updates)
      }
    },
    [activeSnapshotId, level, provinceCountryMap, countryProvinceMap, toolMode, selectedCountry, patchMutation],
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
      name: '新国家',
      color,
      description: '',
    })
  }, [countries.length, upsertCountryMutation])

  const handleCreateSnapshot = useCallback(() => {
    const id = `snap_${Date.now().toString(36)}`
    createSnapshotMutation.mutate({ id, year: null, description: '新快照' })
  }, [createSnapshotMutation])

  const handleSaveCountryEdit = useCallback(() => {
    if (editingCountry) {
      upsertCountryMutation.mutate(editingCountry)
      setEditingCountry(null)
    }
  }, [editingCountry, upsertCountryMutation])

  // Count assignments per fictional country (for stats)
  const assignmentCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const a of assignments) {
      counts.set(a.country_id, (counts.get(a.country_id) || 0) + 1)
    }
    return counts
  }, [assignments])

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const loading = adm1Loading || terrLoading

  return (
    <div className="h-screen flex flex-col bg-gray-900 text-white overflow-hidden">
      {/* Top bar */}
      <header className="flex items-center gap-4 px-4 py-2 bg-gray-800 border-b border-gray-700 shrink-0">
        <button
          onClick={() => navigate(`/worlds/${world}`)}
          className="text-gray-400 hover:text-white text-sm"
        >
          ← 返回
        </button>
        <h1 className="text-lg font-semibold">
          文明地图 — {world}
          {branch && <span className="text-gray-400 text-sm ml-2">/{branch}</span>}
          {staticMode && (
            <span className="text-xs bg-gray-700 text-gray-400 px-2 py-0.5 rounded ml-2">
              只读
            </span>
          )}
        </h1>

        {/* Level selector */}
        <div className="ml-auto flex items-center gap-2">
          <label className="text-sm text-gray-400">层级:</label>
          <select
            value={level}
            onChange={(e) => setLevel(e.target.value as BoundaryLevel)}
            className="bg-gray-700 text-white text-sm rounded px-2 py-1"
          >
            {(availableLevels || ['adm0', 'adm1']).map((l) => (
              <option key={l} value={l}>
                {l === 'adm0' ? '国界' : l === 'adm1' ? '省/州' : '区/县'}
              </option>
            ))}
          </select>
          {level === 'adm0' && (
            <span className="text-xs text-yellow-400">
              ⚡ 以国家为单位涂色
            </span>
          )}
        </div>
      </header>

      {/* Main content: 3-panel layout */}
      <div className="flex flex-1 min-h-0">
        {/* Left panel: Country palette + tools */}
        <aside className="w-64 bg-gray-800 border-r border-gray-700 flex flex-col overflow-y-auto shrink-0">
          {/* Tools */}
          <div className="p-3 border-b border-gray-700">
            <h2 className="text-xs uppercase text-gray-500 mb-2">工具</h2>
            <div className="flex gap-1">
              {([
                ['paint', '涂色', '🖌️'],
                ['erase', '擦除', '🧹'],
                ['select', '选择', '👆'],
              ] as const).map(([mode, label, icon]) => (
                <button
                  key={mode}
                  onClick={() => setToolMode(mode)}
                  className={`flex-1 text-xs py-1.5 rounded ${
                    toolMode === mode
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  }`}
                >
                  {icon} {label}
                </button>
              ))}
            </div>
          </div>

          {/* Country palette */}
          <div className="p-3 flex-1">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xs uppercase text-gray-500">国家</h2>
              {!staticMode && (
                <button
                  onClick={handleAddCountry}
                  className="text-xs text-blue-400 hover:text-blue-300"
                >
                  + 新增
                </button>
              )}
            </div>

            {countries.length === 0 && (
              <p className="text-xs text-gray-500">
                点击 "+ 新增" 创建架空国家
              </p>
            )}

            <div className="space-y-1">
              {countries.map((c) => (
                <div
                  key={c.id}
                  className={`flex items-center gap-2 px-2 py-1.5 rounded text-sm group ${
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
                      {assignmentCounts.get(c.id) || 0}
                    </span>
                  </button>
                  <button
                    onClick={() => setEditingCountry({ ...c })}
                    className="text-gray-500 hover:text-gray-300 text-xs opacity-0 group-hover:opacity-100 shrink-0"
                    title="编辑"
                  >
                    ✏️
                  </button>
                </div>
              ))}
            </div>
          </div>

          {/* Snapshot section */}
          <div className="p-3 border-t border-gray-700">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xs uppercase text-gray-500">时间快照</h2>
              {!staticMode && (
                <button
                  onClick={handleCreateSnapshot}
                  className="text-xs text-blue-400 hover:text-blue-300"
                >
                  + 新增
                </button>
              )}
            </div>

            {(!territory?.snapshots || territory.snapshots.length === 0) && (
              <p className="text-xs text-gray-500">
                点击 "+ 新增" 创建时间快照
              </p>
            )}

            <div className="space-y-1">
              {territory?.snapshots.map((s) => (
                <div
                  key={s.id}
                  className={`group/snap flex items-center text-xs px-2 py-1 rounded cursor-pointer ${
                    s.id === activeSnapshotId
                      ? 'bg-blue-900/50 text-blue-300'
                      : 'text-gray-400 hover:bg-gray-700'
                  }`}
                >
                  <span className="flex-1 truncate">
                    {s.year ? `${s.year}年` : s.id} — {s.description || '(无描述)'}
                  </span>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setEditingSnapshot({ ...s })
                    }}
                    className="text-gray-500 hover:text-gray-300 opacity-0 group-hover/snap:opacity-100 shrink-0 ml-1"
                    title="编辑"
                  >
                    ✏️
                  </button>
                </div>
              ))}
            </div>
          </div>
        </aside>

        {/* Center: Map */}
        <main className="flex-1 min-w-0">
          <CivLeafletMap
            adm1Geojson={adm1Geojson || null}
            adm0Geojson={adm0Geojson || null}
            level={level}
            countries={countries}
            assignments={assignments}
            provinceCountryMap={provinceCountryMap}
            countryProvinceMap={countryProvinceMap}
            toolMode={toolMode}
            onProvinceHover={handleProvinceHover}
            onProvincePaint={handleProvincePaint}
            loading={loading}
          />
        </main>

        {/* Right panel: Province inspector */}
        <aside className="w-56 bg-gray-800 border-l border-gray-700 p-3 overflow-y-auto shrink-0">
          <h2 className="text-xs uppercase text-gray-500 mb-2">
            {level === 'adm0' ? '国家信息' : '省区信息'}
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
                  省份: {hoveredProvince.painted_count}/{hoveredProvince.province_count} 已涂色
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
                  未分配
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-gray-500">
              将鼠标移到地图上的{level === 'adm0' ? '国家' : '省区'}查看详情
            </p>
          )}

          {/* Stats */}
          <div className="mt-6 pt-4 border-t border-gray-700">
            <h2 className="text-xs uppercase text-gray-500 mb-2">统计</h2>
            <div className="space-y-1 text-xs text-gray-400">
              <div>国家: {countries.length}</div>
              <div>已分配省区: {assignments.length}</div>
              <div>
                快照: {territory?.snapshots.length || 0}
              </div>
            </div>
          </div>

          {/* No snapshot warning */}
          {!activeSnapshotId && (
            <div className="mt-4 p-2 bg-yellow-900/30 border border-yellow-700/50 rounded text-xs text-yellow-300">
              ⚠️ 请先创建时间快照才能涂色
            </div>
          )}
        </aside>
      </div>

      {/* Status bar */}
      <footer className="flex items-center gap-4 px-4 py-1 bg-gray-800 border-t border-gray-700 text-xs text-gray-400 shrink-0">
        <span>
          {selectedCountry
            ? `🖌️ 涂色: ${selectedCountry.name}`
            : toolMode === 'erase'
              ? '🧹 擦除模式'
              : '👆 选择模式'}
        </span>
        {activeSnapshotId && (
          <span>📅 当前快照: {activeSnapshotId}</span>
        )}
        <span className="ml-auto">
          {adm1Geojson ? `${adm1Geojson.features.length} 个省区` : '加载中...'}
          {level === 'adm0' && adm0Geojson ? ` · ${adm0Geojson.features.length} 国界` : ''}
        </span>
      </footer>

      {/* Snapshot edit modal */}
      {editingSnapshot && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[2000]">
          <div className="bg-gray-800 rounded-lg p-6 w-80 shadow-xl border border-gray-600">
            <h3 className="text-lg font-semibold mb-4">编辑快照</h3>

            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">年份</label>
                <input
                  type="number"
                  value={editingSnapshot.year ?? ''}
                  onChange={(e) =>
                    setEditingSnapshot({
                      ...editingSnapshot,
                      year: e.target.value ? parseInt(e.target.value, 10) : null,
                    })
                  }
                  placeholder="可选"
                  className="w-full bg-gray-700 text-white rounded px-3 py-1.5 text-sm border border-gray-600 focus:border-blue-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-400 mb-1">描述</label>
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
                取消
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
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Country edit modal */}
      {editingCountry && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[2000]">
          <div className="bg-gray-800 rounded-lg p-6 w-80 shadow-xl border border-gray-600">
            <h3 className="text-lg font-semibold mb-4">编辑国家</h3>

            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-400 mb-1">名称</label>
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
                <label className="block text-xs text-gray-400 mb-1">颜色</label>
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
                <label className="block text-xs text-gray-400 mb-1">描述</label>
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
                  if (confirm('确定删除该国家？所有相关领土分配也会被清除。')) {
                    deleteCountryMutation.mutate(editingCountry.id)
                  }
                }}
                className="text-sm text-red-400 hover:text-red-300"
              >
                删除国家
              </button>
              <div className="flex gap-2">
                <button
                  onClick={() => setEditingCountry(null)}
                  className="px-3 py-1.5 text-sm text-gray-300 bg-gray-700 rounded hover:bg-gray-600"
                >
                  取消
                </button>
                <button
                  onClick={handleSaveCountryEdit}
                  className="px-3 py-1.5 text-sm text-white bg-blue-600 rounded hover:bg-blue-500"
                >
                  保存
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
