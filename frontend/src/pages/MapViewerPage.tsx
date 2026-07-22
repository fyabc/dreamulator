/**
 * MapViewerPage — full-page read-only map viewer with Three.js terrain + SVG overlay.
 *
 * Route: /worlds/:worldName/map and /worlds/:worldName/map/:planetId
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import BranchSelector from '../components/BranchSelector'
import MapViewer, { type CursorInfo } from '../components/map/MapViewer'
import MapLayerPanel, { type LayerState } from '../components/map/MapLayerPanel'
import MapCellInspector from '../components/map/MapCellInspector'
import MapStatusBar from '../components/map/MapStatusBar'
import MapMinimap from '../components/map/MapMinimap'
import { decodePngToFloat32 } from '../viewers/map/utils/imageCodec'
import type { ProjectionType } from '../viewers/map/utils/projection'
import type { VoronoiCell, TectonicPlate } from '../viewers/map/types'

export default function MapViewerPage() {
  const { worldName, planetId: routePlanetId } = useParams<{
    worldName: string
    planetId?: string
  }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  // Initialize branch from URL search params (persists across refresh/navigation)
  const [selectedBranch, setSelectedBranch] = useState<string | null>(
    () => searchParams.get('branch') ?? null
  )
  const [selectedPlanet, setSelectedPlanet] = useState<string>(routePlanetId ?? '')

  // Sync branch selection to URL
  useEffect(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (selectedBranch) {
        next.set('branch', selectedBranch)
      } else {
        next.delete('branch')
      }
      return next
    }, { replace: true })
  }, [selectedBranch, setSearchParams])
  const [cursor, setCursor] = useState<CursorInfo | null>(null)
  const [hoveredCell, setHoveredCell] = useState<number | null>(null)
  const [selectedCells, setSelectedCells] = useState<Set<number>>(new Set())
  const [projection, setProjection] = useState<ProjectionType>('equirectangular')

  const [layerState, setLayerState] = useState<LayerState>({
    colorMode: 'terrain',
  })

  // Decoded elevation data (for rendering)
  const [localElevation, setLocalElevation] = useState<Float32Array | null>(null)

  // Left panel drawer (mobile only)
  const [leftPanelOpen, setLeftPanelOpen] = useState(false)

  // Effective zoom (reported by MapViewer for status bar display)
  const [displayZoom, setDisplayZoom] = useState(1)

  // View state for minimap (reported by MapViewer)
  const [viewState, setViewState] = useState<{
    mapCenter: { lon: number; lat: number }
    zoom: number
    containerWidth: number
    containerHeight: number
  }>({
    mapCenter: { lon: 0, lat: 0 },
    zoom: 1,
    containerWidth: 800,
    containerHeight: 400,
  })

  // --- Data fetching ---

  const { data: mapPlanets } = useQuery({
    queryKey: ['mapPlanets', worldName, selectedBranch],
    queryFn: () => api.listMapPlanets(worldName!, selectedBranch),
    enabled: !!worldName,
  })

  // World planet definitions (for default planet ID)
  const { data: worldPlanets } = useQuery({
    queryKey: ['worldPlanets', worldName, selectedBranch],
    queryFn: () => api.getPlanets(worldName!, selectedBranch),
    enabled: !!worldName,
  })

  // Auto-select first planet if none selected
  useEffect(() => {
    if (!selectedPlanet) {
      if (mapPlanets && mapPlanets.length > 0) {
        setSelectedPlanet(mapPlanets[0])
      } else if (worldPlanets && worldPlanets.length > 0) {
        setSelectedPlanet(worldPlanets[0].id)
      }
    }
  }, [mapPlanets, worldPlanets, selectedPlanet])

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

  // Decode elevation blob to Float32Array for rendering
  useEffect(() => {
    if (!elevationBlob) {
      setLocalElevation(null)
      return
    }
    decodePngToFloat32(elevationBlob).then(({ data }) => {
      setLocalElevation(data)
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

  // CVT mesh data for polygon rendering
  const { data: cvtMesh } = useQuery({
    queryKey: ['cvtMesh', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getCvtMesh(worldName!, selectedPlanet, selectedBranch),
    enabled: !!worldName && !!selectedPlanet,
    retry: false,
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

  // Use cvtMesh.cells (rich property set) when available; fall back to voronoi endpoint
  const voronoiCells: VoronoiCell[] = useMemo(
    () => cvtMesh?.cells ?? voronoi?.cells ?? [],
    [cvtMesh, voronoi],
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

  // Display name for the currently selected planet
  const currentPlanetName = useMemo(() => {
    if (!selectedPlanet || !worldPlanets) return null
    const p = worldPlanets.find((pl: { id: string }) => pl.id === selectedPlanet)
    return p?.name ?? null
  }, [selectedPlanet, worldPlanets])

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
          {currentPlanetName ?? selectedPlanet ?? '地图'}
        </h1>
        <span className="text-xs text-gray-600">地图查看器</span>

        <div className="flex-1" />

        {/* Projection selector */}
        <select
          value={projection}
          onChange={(e) => setProjection(e.target.value as ProjectionType)}
          className="px-2 py-1 rounded bg-space-surface text-sm text-gray-300 border border-space-border"
        >
          <option value="equirectangular">等距圆柱</option>
          <option value="mollweide">摩尔威德</option>
          <option value="robinson">罗宾逊</option>
        </select>

        {/* Planet selector */}
        {worldPlanets && worldPlanets.length > 0 && (
          <select
            value={selectedPlanet}
            onChange={(e) => {
              setSelectedPlanet(e.target.value)
              const qs = selectedBranch ? `?branch=${encodeURIComponent(selectedBranch)}` : ''
              navigate(`/worlds/${worldName}/map/${e.target.value}${qs}`)
            }}
            className="px-2 py-1 rounded bg-space-surface text-sm text-gray-300 border border-space-border"
          >
            {worldPlanets.map((p: { id: string; name?: string }) => (
              <option key={p.id} value={p.id}>
                {p.name ?? p.id}
                {mapPlanets?.includes(p.id) ? '' : ' (无地图)'}
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
                <p>
                  {selectedPlanet
                    ? `${currentPlanetName ?? selectedPlanet} 暂无地图数据`
                    : '该行星暂无地图数据'}
                </p>
              </div>
            ) : (
              <>
                <div className="flex-1 min-h-0">
                  <MapViewer
                    metadata={meta}
                    elevation={localElevation}
                    voronoiCells={voronoiCells}
                    cvtMesh={cvtMesh}
                    colorMode={layerState.colorMode}
                    projection={projection}

                    onCursorMove={setCursor}
                    onCellHover={setHoveredCell}
                    onCellClick={handleCellClick}
                    hoveredCell={hoveredCell}
                    selectedCells={selectedCells}
                    onZoomChange={setDisplayZoom}
                    onViewStateChange={setViewState}
                  />
                </div>
                <MapStatusBar cursor={cursor} zoom={displayZoom} hoveredCell={hoveredCellData} />
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
                    图层设置
                  </span>
                  <button
                    onClick={() => setLeftPanelOpen(false)}
                    className="text-gray-500 hover:text-gray-300 text-lg leading-none"
                  >
                    ✕
                  </button>
                </div>
                <MapLayerPanel
                  state={layerState}
                  onChange={setLayerState}
                />
              </div>
            </>
          )}
        </div>

        {/* === Desktop layout (≥ md, hidden by default) === */}
        <div className="hidden md:flex flex-1 min-h-0">
          {/* Left panel: layers */}
          <div className="w-56 shrink-0 bg-space-panel/50 border-r border-space-border overflow-y-auto p-3 space-y-4">
            <MapLayerPanel
              state={layerState}
              onChange={setLayerState}
            />
          </div>

          {/* Center: map viewer */}
          <div className="flex-1 flex flex-col min-w-0">
            {loadingElevation ? (
              <div className="flex-1 flex items-center justify-center text-gray-500">
                加载地图数据...
              </div>
            ) : !localElevation ? (
              <div className="flex-1 flex flex-col items-center justify-center text-gray-500 gap-4">
                <p>
                  {selectedPlanet
                    ? `${currentPlanetName ?? selectedPlanet} 暂无地图数据`
                    : '该行星暂无地图数据'}
                </p>
              </div>
            ) : (
              <>
                <div className="flex-1 min-h-0">
                  <MapViewer
                    metadata={meta}
                    elevation={localElevation}
                    voronoiCells={voronoiCells}
                    cvtMesh={cvtMesh}
                    colorMode={layerState.colorMode}
                    projection={projection}

                    onCursorMove={setCursor}
                    onCellHover={setHoveredCell}
                    onCellClick={handleCellClick}
                    hoveredCell={hoveredCell}
                    selectedCells={selectedCells}
                    onZoomChange={setDisplayZoom}
                    onViewStateChange={setViewState}
                  />
                </div>
                <MapStatusBar cursor={cursor} zoom={displayZoom} hoveredCell={hoveredCellData} />
              </>
            )}
          </div>

          {/* Right panel: cell inspector + minimap */}
          <div className="w-52 shrink-0 bg-space-panel/50 border-l border-space-border flex flex-col min-h-0">
            {/* Scrollable inspector area */}
            <div className="flex-1 min-h-0 overflow-y-auto p-3">
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                单元格详情
              </h3>
              <MapCellInspector
                cell={hoveredCellData}
                plate={hoveredPlate}
                cvtMesh={cvtMesh ?? null}
                planetName={currentPlanetName}
              />
              {selectedCells.size > 0 && (
                <div className="mt-4 pt-3 border-t border-space-border">
                  <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                    已选择
                  </h3>
                  <p className="text-xs text-gray-400">
                    {selectedCells.size} 个单元格
                  </p>
                </div>
              )}
            </div>

            {/* Minimap — pinned at bottom */}
            {localElevation && (
              <div className="shrink-0 border-t border-space-border p-3">
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  鸟瞰图
                </h3>
                <MapMinimap
                  elevation={localElevation}
                  width={meta?.width ?? 2048}
                  height={meta?.height ?? 1024}
                  seaLevel={meta?.sea_level_m ?? 0.0}
                  mapCenter={viewState.mapCenter}
                  zoom={viewState.zoom}
                  containerWidth={viewState.containerWidth}
                  containerHeight={viewState.containerHeight}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
