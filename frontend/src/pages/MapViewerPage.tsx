/**
 * MapViewerPage — full-page read-only map viewer with Three.js terrain + SVG overlay.
 *
 * Route: /worlds/:worldName/map and /worlds/:worldName/map/:planetId
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import ImportElevationButton, { type ImportElevationResult } from '../components/map/ImportElevationButton'
import GeographyRasterButton from '../components/map/GeographyRasterButton'
import BranchSelector from '../components/BranchSelector'
import MapViewer, { type CursorInfo } from '../components/map/MapViewer'
import MapLayerPanel, { type LayerState } from '../components/map/MapLayerPanel'
import MapCellInspector from '../components/map/MapCellInspector'
import HelpPanel from '../components/map/HelpPanel'
import MapStatusBar from '../components/map/MapStatusBar'
import MapMinimap from '../components/map/MapMinimap'
import SunControl from '../components/map/SunControl'
import { solarDeclinationDeg } from '../viewers/utils/solar'
import { PROJECTION_HELP } from '../components/map/helpContent'
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

  // Derive branch from URL (not local state) — stays in sync with browser back/forward
  const selectedBranch = searchParams.get('branch') || null
  const setSelectedBranch = (branch: string | null) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (branch) next.set('branch', branch)
      else next.delete('branch')
      return next
    }, { replace: true })
  }
  const [selectedPlanet, setSelectedPlanet] = useState<string>(routePlanetId ?? '')
  const [cursor, setCursor] = useState<CursorInfo | null>(null)
  const [hoveredCell, setHoveredCell] = useState<number | null>(null)
  const [selectedCells, setSelectedCells] = useState<Set<number>>(new Set())
  const [projection, setProjection] = useState<ProjectionType>('equirectangular')

  // --- Sun / day-night state (synced to URL: ?sun=&season=&night=) ---
  const [sunLongitudeDeg, setSunLongitudeDeg] = useState(() => {
    const v = Number(searchParams.get('sun'))
    return Number.isFinite(v) ? v : 0
  })
  const [seasonDeg, setSeasonDeg] = useState(() => {
    const v = Number(searchParams.get('season'))
    return Number.isFinite(v) ? v : 0
  })
  const [dayNightEnabled, setDayNightEnabled] = useState(() => searchParams.get('night') === '1')

  // Keep the URL in sync so lighting is shareable and carries across 2D↔3D nav.
  useEffect(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (sunLongitudeDeg !== 0) next.set('sun', String(sunLongitudeDeg))
      else next.delete('sun')
      if (seasonDeg !== 0) next.set('season', String(seasonDeg))
      else next.delete('season')
      if (dayNightEnabled) next.set('night', '1')
      else next.delete('night')
      return next
    }, { replace: true })
  }, [sunLongitudeDeg, seasonDeg, dayNightEnabled, setSearchParams])

  const [layerState, setLayerState] = useState<LayerState>({
    layers: { terrain: 1, landsea: 0, plates: 0, boundaries: 0, koppen: 0 },
  })

  // Decoded elevation data (for rendering)
  const [localElevation, setLocalElevation] = useState<Float32Array | null>(null)

  // Left panel drawer (mobile only)
  const [leftPanelOpen, setLeftPanelOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)

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
  const { data: worldPlanets, isError: worldPlanetsError } = useQuery({
    queryKey: ['worldPlanets', worldName, selectedBranch],
    queryFn: () => api.getPlanets(worldName!, selectedBranch),
    enabled: !!worldName,
  })

  // Auto-select / reconcile the active planet:
  // - none selected → first available map (or first defined planet if no maps)
  // - selected planet has no map data in the current branch → redirect to the
  //   branch's first available map.  Map IDs differ per branch (e.g.
  //   climate-dev stores "planet_earth" while terrain-dev stores "earth"),
  //   so a branch switch can leave a stale ID in the URL that 404s.
  useEffect(() => {
    if (selectedPlanet && mapPlanets && mapPlanets.includes(selectedPlanet)) return
    if (selectedPlanet && !mapPlanets) return // list not loaded yet — wait

    if (mapPlanets && mapPlanets.length > 0) {
      const target = mapPlanets[0]
      setSelectedPlanet(target)
      const qs = searchParams.toString()
      navigate(`/worlds/${worldName}/map/${target}${qs ? `?${qs}` : ''}`, {
        replace: true,
      })
      return
    }
    // No maps available anywhere — fall back to a defined planet ID
    if (!selectedPlanet && worldPlanets && worldPlanets.length > 0) {
      setSelectedPlanet(worldPlanets[0].id)
    }
  }, [mapPlanets, worldPlanets, selectedPlanet, navigate, worldName, searchParams])

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
    let cancelled = false
    decodePngToFloat32(elevationBlob).then(({ data }) => {
      if (!cancelled) setLocalElevation(data)
    }).catch(() => {
      // Decode failure (e.g. corrupted PNG) → treat as no data
      if (!cancelled) setLocalElevation(null)
    })
    return () => { cancelled = true }
  }, [elevationBlob])

  const { data: voronoi } = useQuery({
    queryKey: ['voronoi', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getVoronoi(worldName!, selectedPlanet, selectedBranch),
    enabled: !!worldName && !!selectedPlanet,
    retry: false,
  })

  const { data: plates, isError: platesError } = useQuery({
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

  // --- Heightmap import (write op; live mode only) ---
  const queryClient = useQueryClient()
  const [importMsg, setImportMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const handleImported = useCallback(
    (r: ImportElevationResult) => {
      if (r.ok) {
        for (const key of ['elevationBlob', 'voronoi', 'cvtMesh', 'plates', 'mapMeta']) {
          queryClient.invalidateQueries({
            queryKey: [key, worldName, selectedPlanet, selectedBranch],
          })
        }
        const res = r.output_resolution
          ? `，输出 ${r.output_resolution[0]}×${r.output_resolution[1]}`
          : ''
        const stale = r.stale_layers?.length
          ? `；已标记过期：${r.stale_layers.join('、')}`
          : ''
        setImportMsg({
          ok: true,
          text: `已导入 ${r.source_format ?? '高度图'}${res}${stale}。导入的高度图不含板块构造数据。`,
        })
      } else {
        setImportMsg({ ok: false, text: `导入失败：${r.detail ?? '未知错误（格式不支持？）'}` })
      }
    },
    [queryClient, worldName, selectedPlanet, selectedBranch]
  )

  // --- Interaction handlers ---

  const handleCellClick = useCallback((cellId: number, ctrlKey: boolean) => {
    setSelectedCells((prev) => {
      if (ctrlKey) {
        // Ctrl+double-click → toggle this cell in/out of selection
        const next = new Set(prev)
        if (prev.has(cellId)) next.delete(cellId)
        else next.add(cellId)
        return next
      }
      // Plain double-click → replace selection with this cell
      return new Set([cellId])
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

  // Planet axial tilt (amplitude of seasonal declination) + current declination.
  const axialTiltDeg = useMemo(() => {
    if (!worldPlanets) return 0
    const p = worldPlanets.find(
      (pl: { id: string; axial_tilt_deg?: number }) => pl.id === selectedPlanet,
    )
    return p?.axial_tilt_deg ?? 0
  }, [worldPlanets, selectedPlanet])
  const solarDeclination = solarDeclinationDeg(seasonDeg, axialTiltDeg)

  // Forward current lighting (sun/season/night) + branch to the 3D globe link.
  const globeQS = searchParams.toString() ? `?${searchParams.toString()}` : ''

  // Debug / A-B flag: ?reproject=cpu forces the legacy CPU reprojection
  // (Mollweide/Robinson) for comparison with the GPU result.  NOT a no-GPU
  // fallback — the map display always requires WebGL.
  const forceCpuReproject = searchParams.get('reproject') === 'cpu'

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
          {PROJECTION_HELP.map((p) => (
            <option key={p.id} value={p.id}>{p.label}</option>
          ))}
        </select>

        {/* 3D Globe button */}
        {selectedPlanet && (
          <Link
            to={`/worlds/${worldName}/globe/${selectedPlanet}${globeQS}`}
            className="px-3 py-1 text-sm rounded-lg bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors"
            title="3D 球面视图"
          >
            🌐 3D
          </Link>
        )}

        {/* Import external heightmap (live mode only) */}
        {selectedPlanet && (
          <ImportElevationButton
            worldName={worldName!}
            planetId={selectedPlanet}
            branch={selectedBranch}
            onImported={handleImported}
          />
        )}

        {/* Upload dense anchoring grayscale (next generation run) */}
        <GeographyRasterButton
          worldName={worldName!}
          branch={selectedBranch}
          onUploaded={(r) =>
            setImportMsg(
              r.ok
                ? {
                    ok: true,
                    text: `锚定灰度图已保存（${r.source_format ?? ''}）。将于下次地形生成时与 geography.yaml 叠加生效。`,
                  }
                : { ok: false, text: `上传失败：${r.detail ?? '未知错误'}` }
            )
          }
        />

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

        {/* Help button */}
        <button
          onClick={() => setHelpOpen((v) => !v)}
          className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold border transition-colors ${
            helpOpen
              ? 'bg-neon-cyan/20 text-neon-cyan border-neon-cyan/40'
              : 'bg-space-surface text-gray-400 border-space-border hover:text-neon-cyan hover:border-neon-cyan/30'
          }`}
          title="帮助"
        >
          ?
        </button>

      </div>

      {/* Error banner */}
      {worldPlanetsError && (
        <div className="bg-red-900/20 border-b border-red-700/30 px-4 py-2 text-sm text-red-300 text-center">
          行星数据加载失败，请检查网络连接或切换分支重试。
        </div>
      )}

      {/* Import result banner */}
      {importMsg && (
        <div
          className={`${
            importMsg.ok
              ? 'bg-green-900/20 border-green-700/30 text-green-300'
              : 'bg-red-900/20 border-red-700/30 text-red-300'
          } border-b px-4 py-2 text-sm text-center`}
        >
          {importMsg.text}
        </div>
      )}

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
                    layers={layerState.layers}
                    projection={projection}

                    onCursorMove={setCursor}
                    onCellHover={setHoveredCell}
                    onCellClick={handleCellClick}
                    hoveredCell={hoveredCell}
                    selectedCells={selectedCells}
                    sunLongitudeDeg={sunLongitudeDeg}
                    solarDeclinationDeg={solarDeclination}
                    dayNight={dayNightEnabled}
                    forceCpuReproject={forceCpuReproject}
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
                {platesError && selectedPlanet && (
                  <div className="text-xs text-gray-500 pt-2">
                    该地图无板块构造数据（导入的高度图不含 plates）。
                  </div>
                )}
                <div className="pt-3 border-t border-space-border">
                  <SunControl
                    sunLongitudeDeg={sunLongitudeDeg}
                    onLongitudeChange={setSunLongitudeDeg}
                    seasonDeg={seasonDeg}
                    onSeasonChange={setSeasonDeg}
                    axialTiltDeg={axialTiltDeg}
                    enabled={dayNightEnabled}
                    onEnabledChange={setDayNightEnabled}
                  />
                </div>
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
            {platesError && selectedPlanet && (
              <div className="text-xs text-gray-500 pt-2">
                该地图无板块构造数据（导入的高度图不含 plates）。
              </div>
            )}
            <div className="pt-3 border-t border-space-border">
              <SunControl
                sunLongitudeDeg={sunLongitudeDeg}
                onLongitudeChange={setSunLongitudeDeg}
                seasonDeg={seasonDeg}
                onSeasonChange={setSeasonDeg}
                axialTiltDeg={axialTiltDeg}
                enabled={dayNightEnabled}
                onEnabledChange={setDayNightEnabled}
              />
            </div>
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
                    layers={layerState.layers}
                    projection={projection}

                    onCursorMove={setCursor}
                    onCellHover={setHoveredCell}
                    onCellClick={handleCellClick}
                    hoveredCell={hoveredCell}
                    selectedCells={selectedCells}
                    sunLongitudeDeg={sunLongitudeDeg}
                    solarDeclinationDeg={solarDeclination}
                    dayNight={dayNightEnabled}
                    forceCpuReproject={forceCpuReproject}
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

        {/* Help panel overlay */}
        {helpOpen && <HelpPanel onClose={() => setHelpOpen(false)} />}
      </div>
    </div>
  )
}
