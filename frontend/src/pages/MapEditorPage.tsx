/**
 * MapEditorPage — full-page map editor with Three.js terrain + SVG overlay.
 *
 * Route: /worlds/:worldName/map and /worlds/:worldName/map/:planetId
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { isStaticMode } from '../api/mode'
import BranchSelector from '../components/BranchSelector'
import MapViewer, { type CursorInfo } from '../components/map/MapViewer'
import MapLayerPanel, { type LayerState } from '../components/map/MapLayerPanel'
import MapEditingTools from '../components/map/MapEditingTools'
import MapCellInspector from '../components/map/MapCellInspector'
import MapStatusBar from '../components/map/MapStatusBar'
import MapOnboardingGuide, {
  isOnboardingDismissed,
} from '../components/map/MapOnboardingGuide'
import { decodePngToFloat32, encodeFloat32ToPng } from '../viewers/map/utils/imageCodec'
import type { BrushConfig, VoronoiCell, TectonicPlate } from '../viewers/map/types'

export default function MapEditorPage() {
  const { worldName, planetId: routePlanetId } = useParams<{
    worldName: string
    planetId?: string
  }>()
  const navigate = useNavigate()
  const staticMode = isStaticMode()
  const queryClient = useQueryClient()

  const [selectedBranch, setSelectedBranch] = useState<string | null>(null)
  const [selectedPlanet, setSelectedPlanet] = useState<string>(routePlanetId ?? '')
  const [cursor, setCursor] = useState<CursorInfo | null>(null)
  const [hoveredCell, setHoveredCell] = useState<number | null>(null)
  const [selectedCells, setSelectedCells] = useState<Set<number>>(new Set())

  const [layerState, setLayerState] = useState<LayerState>({
    colorMode: 'terrain',
    showVoronoi: false,
    showPlates: false,
    showFeatures: false,
  })

  const [brushConfig, setBrushConfig] = useState<BrushConfig>({
    tool: 'raise',
    radius: 20,
    strength: 0.3,
    hardness: 0.5,
  })

  // Local elevation data (for unsaved changes tracking)
  const [localElevation, setLocalElevation] = useState<Float32Array | null>(null)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)

  // Left panel drawer (mobile only)
  const [leftPanelOpen, setLeftPanelOpen] = useState(false)

  // Effective zoom (reported by MapViewer for status bar display)
  const [displayZoom, setDisplayZoom] = useState(1)

  // Onboarding guide
  const [showOnboarding, setShowOnboarding] = useState(!isOnboardingDismissed())

  // --- Data fetching ---

  const { data: mapPlanets } = useQuery({
    queryKey: ['mapPlanets', worldName, selectedBranch],
    queryFn: () => api.listMapPlanets(worldName!, selectedBranch),
    enabled: !!worldName,
  })

  // Auto-select first planet if none selected
  useEffect(() => {
    if (!selectedPlanet && mapPlanets && mapPlanets.length > 0) {
      setSelectedPlanet(mapPlanets[0])
    }
  }, [mapPlanets, selectedPlanet])

  const { data: meta } = useQuery({
    queryKey: ['mapMeta', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getMapMeta(worldName!, selectedPlanet, selectedBranch),
    enabled: !!worldName && !!selectedPlanet,
  })

  const { data: elevationBlob, isLoading: loadingElevation } = useQuery({
    queryKey: ['elevationBlob', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getElevationBlob(worldName!, selectedPlanet, selectedBranch),
    enabled: !!worldName && !!selectedPlanet,
    retry: false,
  })

  // Decode elevation blob to Float32Array
  useEffect(() => {
    if (!elevationBlob) {
      setLocalElevation(null)
      return
    }
    decodePngToFloat32(elevationBlob).then(({ data }) => {
      setLocalElevation(data)
      setHasUnsavedChanges(false)
    })
  }, [elevationBlob])

  const { data: voronoi } = useQuery({
    queryKey: ['voronoi', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getVoronoi(worldName!, selectedPlanet, selectedBranch),
    enabled: !!worldName && !!selectedPlanet,
    retry: false,
  })

  const { data: plates } = useQuery({
    queryKey: ['plates', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getPlates(worldName!, selectedPlanet, selectedBranch),
    enabled: !!worldName && !!selectedPlanet,
    retry: false,
  })

  const { data: features } = useQuery({
    queryKey: ['features', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getFeatures(worldName!, selectedPlanet, selectedBranch),
    enabled: !!worldName && !!selectedPlanet,
    retry: false,
  })

  // --- Mutations ---

  const generateMutation = useMutation({
    mutationFn: (params: Record<string, any>) =>
      api.generateTerrain(worldName!, selectedPlanet, params, selectedBranch),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['elevationBlob', worldName, selectedPlanet],
      })
      queryClient.invalidateQueries({
        queryKey: ['voronoi', worldName, selectedPlanet],
      })
      queryClient.invalidateQueries({
        queryKey: ['plates', worldName, selectedPlanet],
      })
      queryClient.invalidateQueries({
        queryKey: ['mapMeta', worldName, selectedPlanet],
      })
      queryClient.invalidateQueries({
        queryKey: ['mapPlanets', worldName],
      })
    },
  })

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!localElevation || !meta) return
      const pngBlob = await encodeFloat32ToPng(localElevation, meta.width, meta.height)
      return api.saveElevation(worldName!, selectedPlanet, pngBlob, selectedBranch)
    },
    onSuccess: () => {
      setHasUnsavedChanges(false)
      queryClient.invalidateQueries({
        queryKey: ['elevationBlob', worldName, selectedPlanet],
      })
    },
  })

  // --- Interaction handlers ---

  const handleCellClick = useCallback((cellId: number, shiftKey: boolean) => {
    setSelectedCells((prev) => {
      const next = new Set(shiftKey ? prev : [])
      if (prev.has(cellId) && shiftKey) {
        next.delete(cellId)
      } else {
        next.add(cellId)
      }
      return next
    })
  }, [])

  const voronoiCells: VoronoiCell[] = useMemo(
    () => voronoi?.cells ?? [],
    [voronoi],
  )

  const tectonicPlates: TectonicPlate[] = useMemo(
    () => (plates as TectonicPlate[]) ?? [],
    [plates],
  )

  const hoveredCellData = useMemo(() => {
    if (hoveredCell === null) return null
    return voronoiCells.find((c) => c.id === hoveredCell) ?? null
  }, [voronoiCells, hoveredCell])

  const hoveredPlate = useMemo(() => {
    if (!hoveredCellData?.plate_id) return null
    return tectonicPlates.find((p) => p.id === hoveredCellData.plate_id) ?? null
  }, [tectonicPlates, hoveredCellData])

  if (!worldName) {
    return <div className="text-center py-12 text-gray-400">未选择世界</div>
  }

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 py-2 bg-space-panel border-b border-space-border shrink-0">
        <Link
          to={`/worlds/${worldName}`}
          className="text-gray-400 hover:text-neon-cyan transition-colors text-sm"
        >
          ← 返回
        </Link>
        <h1 className="text-lg font-bold text-neon-cyan neon-glow-subtle">
          {selectedPlanet || '地图'}
        </h1>
        <span className="text-xs text-gray-600">地图编辑器</span>

        <div className="flex-1" />

        {/* Planet selector */}
        {mapPlanets && mapPlanets.length > 0 && (
          <select
            value={selectedPlanet}
            onChange={(e) => {
              setSelectedPlanet(e.target.value)
              navigate(`/worlds/${worldName}/map/${e.target.value}`)
            }}
            className="px-2 py-1 rounded bg-space-surface text-sm text-gray-300 border border-space-border"
          >
            {mapPlanets.map((p: string) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        )}

        {/* Branch selector */}
        <BranchSelector
          worldName={worldName}
          selectedBranch={selectedBranch}
          onSelect={setSelectedBranch}
        />

        {staticMode && (
          <span className="text-xs px-2 py-0.5 rounded bg-space-surface text-gray-500 border border-space-border">
            只读
          </span>
        )}

        {/* Help button */}
        <button
          onClick={() => setShowOnboarding(true)}
          className="text-gray-500 hover:text-neon-cyan transition-colors w-6 h-6 flex items-center justify-center rounded border border-space-border hover:border-neon-cyan/40 text-xs font-bold"
          title="使用指南"
        >
          ?
        </button>
      </div>

      {/* Main content */}
      <div className="flex flex-1 min-h-0 relative">
        {/* === Mobile layout (default, hidden ≥ md) === */}
        <div className="flex flex-col flex-1 min-w-0 md:hidden">
          {/* Map area — full width */}
          <div className="flex-1 flex flex-col min-h-0">
            {loadingElevation ? (
              <div className="flex-1 flex items-center justify-center text-gray-500">
                加载地图数据...
              </div>
            ) : !localElevation ? (
              <div className="flex-1 flex flex-col items-center justify-center text-gray-500 gap-4">
                <p>该行星暂无地图数据</p>
                {!staticMode && (
                  <button
                    onClick={() =>
                      generateMutation.mutate({
                        num_continents: 3,
                        mountaininess: 0.5,
                        num_plates: 15,
                      })
                    }
                    disabled={generateMutation.isPending}
                    className="px-4 py-2 rounded-lg text-sm font-medium bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 disabled:opacity-50"
                  >
                    {generateMutation.isPending ? '生成中...' : '🌍 生成第一张地图'}
                  </button>
                )}
              </div>
            ) : (
              <>
                <div className="flex-1 min-h-0">
                  <MapViewer
                    metadata={meta}
                    elevation={localElevation}
                    voronoiCells={voronoiCells}
                    plates={tectonicPlates}
                    features={(features as any[]) ?? []}
                    colorMode={layerState.colorMode}
                    showVoronoi={layerState.showVoronoi}
                    showPlates={layerState.showPlates}
                    showFeatures={layerState.showFeatures}
                    readOnly={staticMode}
                    onCursorMove={setCursor}
                    onCellHover={setHoveredCell}
                    onCellClick={handleCellClick}
                    hoveredCell={hoveredCell}
                    selectedCells={selectedCells}
                    onZoomChange={setDisplayZoom}
                  />
                </div>
                <MapStatusBar cursor={cursor} zoom={displayZoom} />
              </>
            )}
          </div>

          {/* Floating toggle button (mobile only, visible when drawer closed) */}
          {!leftPanelOpen && (
            <button
              onClick={() => setLeftPanelOpen(true)}
              className="absolute bottom-4 left-4 z-30 w-10 h-10 rounded-full bg-space-panel border border-space-border flex items-center justify-center text-gray-400 hover:text-neon-cyan hover:border-neon-cyan/40 shadow-lg"
              title="图层设置"
            >
              ☰
            </button>
          )}

          {/* Left panel drawer overlay */}
          {leftPanelOpen && (
            <>
              <div
                className="absolute inset-0 bg-black/50 z-40"
                onClick={() => setLeftPanelOpen(false)}
              />
              <div className="absolute left-0 top-0 bottom-0 w-64 bg-space-panel z-50 overflow-y-auto p-3 space-y-4 shadow-xl">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    图层与工具
                  </span>
                  <button
                    onClick={() => setLeftPanelOpen(false)}
                    className="text-gray-500 hover:text-gray-300 text-lg leading-none"
                  >
                    ✕
                  </button>
                </div>
                <MapLayerPanel state={layerState} onChange={setLayerState} />
                {!staticMode && (
                  <div className="border-t border-space-border pt-4">
                    <MapEditingTools
                      config={brushConfig}
                      onChange={setBrushConfig}
                      onGenerate={() =>
                        generateMutation.mutate({
                          num_continents: 3,
                          mountaininess: 0.5,
                          num_plates: 15,
                        })
                      }
                      onSave={() => saveMutation.mutate()}
                      isGenerating={generateMutation.isPending}
                      isSaving={saveMutation.isPending}
                      hasUnsavedChanges={hasUnsavedChanges}
                    />
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* === Desktop layout (≥ md, hidden by default) === */}
        <div className="hidden md:flex flex-1 min-h-0">
          {/* Left panel: layers + editing tools */}
          <div className="w-56 shrink-0 bg-space-panel/50 border-r border-space-border overflow-y-auto p-3 space-y-4">
            <MapLayerPanel state={layerState} onChange={setLayerState} />
            {!staticMode && (
              <div className="border-t border-space-border pt-4">
                <MapEditingTools
                  config={brushConfig}
                  onChange={setBrushConfig}
                  onGenerate={() =>
                    generateMutation.mutate({
                      num_continents: 3,
                      mountaininess: 0.5,
                      num_plates: 15,
                    })
                  }
                  onSave={() => saveMutation.mutate()}
                  isGenerating={generateMutation.isPending}
                  isSaving={saveMutation.isPending}
                  hasUnsavedChanges={hasUnsavedChanges}
                />
              </div>
            )}
          </div>

          {/* Center: map viewer */}
          <div className="flex-1 flex flex-col min-w-0">
            {loadingElevation ? (
              <div className="flex-1 flex items-center justify-center text-gray-500">
                加载地图数据...
              </div>
            ) : !localElevation ? (
              <div className="flex-1 flex flex-col items-center justify-center text-gray-500 gap-4">
                <p>该行星暂无地图数据</p>
                {!staticMode && (
                  <button
                    onClick={() =>
                      generateMutation.mutate({
                        num_continents: 3,
                        mountaininess: 0.5,
                        num_plates: 15,
                      })
                    }
                    disabled={generateMutation.isPending}
                    className="px-4 py-2 rounded-lg text-sm font-medium bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 disabled:opacity-50"
                  >
                    {generateMutation.isPending ? '生成中...' : '🌍 生成第一张地图'}
                  </button>
                )}
              </div>
            ) : (
              <>
                <div className="flex-1 min-h-0">
                  <MapViewer
                    metadata={meta}
                    elevation={localElevation}
                    voronoiCells={voronoiCells}
                    plates={tectonicPlates}
                    features={(features as any[]) ?? []}
                    colorMode={layerState.colorMode}
                    showVoronoi={layerState.showVoronoi}
                    showPlates={layerState.showPlates}
                    showFeatures={layerState.showFeatures}
                    readOnly={staticMode}
                    onCursorMove={setCursor}
                    onCellHover={setHoveredCell}
                    onCellClick={handleCellClick}
                    hoveredCell={hoveredCell}
                    selectedCells={selectedCells}
                    onZoomChange={setDisplayZoom}
                  />
                </div>
                <MapStatusBar cursor={cursor} zoom={displayZoom} />
              </>
            )}
          </div>

          {/* Right panel: cell inspector */}
          <div className="w-52 shrink-0 bg-space-panel/50 border-l border-space-border overflow-y-auto p-3">
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              单元格详情
            </h3>
            <MapCellInspector
              cell={hoveredCellData}
              plate={hoveredPlate}
              elevMinM={meta?.elevation_min_m ?? -11000}
              elevMaxM={meta?.elevation_max_m ?? 9000}
            />
            {selectedCells.size > 0 && (
              <div className="mt-4 pt-3 border-t border-space-border">
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  已选择
                </h3>
                <p className="text-xs text-gray-400">
                  {selectedCells.size} 个单元格
                </p>
                <p className="text-xs text-gray-600 mt-1 italic">
                  即将推出：省份划分等批量操作
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Onboarding guide overlay */}
      {showOnboarding && (
        <MapOnboardingGuide onClose={() => setShowOnboarding(false)} />
      )}
    </div>
  )
}
