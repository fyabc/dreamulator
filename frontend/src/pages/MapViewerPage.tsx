/**
 * MapViewerPage — full-page read-only map viewer with Three.js terrain + SVG overlay.
 *
 * Route: /worlds/:worldName/map and /worlds/:worldName/map/:planetId
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import ImportElevationButton, { type ImportElevationResult } from '../components/map/ImportElevationButton'
import GeographyRasterButton from '../components/map/GeographyRasterButton'
import BranchSelector from '../components/BranchSelector'
import MapViewer, { type CursorInfo } from '../components/map/MapViewer'
import MapLayerPanel, { type LayerState } from '../components/map/MapLayerPanel'
import MapCellInspector, { MobileCellCard } from '../components/map/MapCellInspector'
import MapStatusBar from '../components/map/MapStatusBar'
import MapMinimap from '../components/map/MapMinimap'
import SunControl from '../components/map/SunControl'
import { solarDeclinationDeg } from '../viewers/utils/solar'
import { PROJECTION_HELP } from '../components/map/helpContent'
import { decodePngToFloat32 } from '../viewers/map/utils/imageCodec'
import type { ProjectionType } from '../viewers/map/utils/projection'
import type { VoronoiCell } from '../viewers/map/types'

export default function MapViewerPage() {
  const { worldName, planetId: routePlanetId } = useParams<{
    worldName: string
    planetId?: string
  }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { t } = useTranslation('map')

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
  /** Last hovered cell — retained so the inspector doesn't reset on mouse-leave. */
  const [lastCell, setLastCell] = useState<number | null>(null)
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
    layers: { terrain: 1, landsea: 0, plates: 0, boundaries: 0, coastlines: 1, rivers: 0.9, koppen: 0, currents: 0, winds: 0, biomes: 0, npp: 0, domesticable: 0, soil: 0, provinces: 0, temperature: 0, precipitation: 0, habitable: 0, agriculture: 0, flow: 0 },
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

  const { data: elevationBlob } = useQuery({
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

  const { isError: platesError } = useQuery({
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

  // River network vector layer (features.json; empty when absent)
  const { data: riverFeatures } = useQuery({
    queryKey: ['riverFeatures', worldName, selectedPlanet, selectedBranch],
    queryFn: async () => {
      const feats = await api.getFeatures(worldName!, selectedPlanet, selectedBranch)
      return feats.filter((f) => f.type === 'river')
    },
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
          ? t('msg.outputResolution', { w: r.output_resolution[0], h: r.output_resolution[1] })
          : ''
        const stale = r.stale_layers?.length
          ? t('msg.staleLayers', { layers: r.stale_layers.join(t('msg.listSeparator')) })
          : ''
        setImportMsg({
          ok: true,
          text: t('msg.importedHeightmap', {
            format: r.source_format ?? t('msg.sourceFormatFallback'),
            resolution: res,
            stale: stale,
          }),
        })
      } else {
        setImportMsg({ ok: false, text: t('msg.importFailed', { detail: r.detail ?? t('msg.importFailedFallback') }) })
      }
    },
    [queryClient, worldName, selectedPlanet, selectedBranch]
  )

  // --- Interaction handlers ---

  const handleCellClick = useCallback((cellId: number, ctrlKey: boolean) => {
    setSelectedCells((prev) => {
      const alreadySelected = prev.has(cellId)
      if (ctrlKey) {
        // Ctrl+double-click → toggle this cell (keep others)
        const next = new Set(prev)
        if (alreadySelected) next.delete(cellId)
        else next.add(cellId)
        return next
      }
      // Plain double-click → clear others, then toggle
      if (alreadySelected && prev.size === 1) {
        // Only this cell selected → deselect it
        return new Set()
      }
      return new Set([cellId])
    })
  }, [])

  // Esc → clear all selections
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedCells(new Set())
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Use cvtMesh.cells (rich property set) when available; fall back to voronoi endpoint
  const voronoiCells: VoronoiCell[] = useMemo(
    () => cvtMesh?.cells ?? voronoi?.cells ?? [],
    [cvtMesh, voronoi],
  )

  // --- Panel state machine ---
  // 0 selected → show hovered cell (null when mouse leaves → planet summary)
  // 1 selected → show that cell (locked, survives mouse leave)
  // >1 selected → show aggregate stats

  const selectedCellData = useMemo(() => {
    if (selectedCells.size === 0) return null
    // Show first selected cell for single-selection detail
    const id = [...selectedCells][0]
    return voronoiCells.find((c) => c.id === id) ?? null
  }, [voronoiCells, selectedCells])

  const hoveredCellData = useMemo(() => {
    if (hoveredCell === null) return null
    return voronoiCells.find((c) => c.id === hoveredCell) ?? null
  }, [voronoiCells, hoveredCell])

  /** Hover handler: track the live hover (highlight) and remember the last cell. */
  const handleCellHover = useCallback((cellId: number | null) => {
    setHoveredCell(cellId)
    if (cellId !== null) setLastCell(cellId)
  }, [])

  const lastCellData = useMemo(() => {
    if (lastCell === null) return null
    return voronoiCells.find((c) => c.id === lastCell) ?? null
  }, [voronoiCells, lastCell])

  /** Cell shown in the inspector: 1 selected → locked; 0 selected → last hovered
   *  (retained on mouse-leave so the panel and its group state persist). */
  const inspectorCell = selectedCells.size === 1
    ? selectedCellData
    : selectedCells.size > 1
      ? null  // triggers MultiCellStats
      : lastCellData

  /** Selected cell objects for aggregate stats (>1 selected). */
  const selectedCellObjects = useMemo(() => {
    if (selectedCells.size <= 1) return undefined
    return [...selectedCells].map((id) => voronoiCells.find((c) => c.id === id)).filter(Boolean) as VoronoiCell[]
  }, [voronoiCells, selectedCells])

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
    return <div className="text-center py-12 text-gray-400">{t('status.noWorld')}</div>
  }

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 py-2 bg-space-panel border-b border-space-border shrink-0">
        <Link
          to={`/worlds/${worldName}`}
          className="text-gray-400 hover:text-neon-cyan transition-colors text-sm"
        >
          {t('action.back')}
        </Link>
        <h1 className="text-lg font-bold text-neon-cyan neon-glow-subtle">
          {currentPlanetName ?? selectedPlanet ?? t('title.mapFallback')}
        </h1>
        <span className="text-xs text-gray-600">{t('title.viewer')}</span>

        <div className="flex-1" />

        {/* 3D Globe button (leftmost in the view-switch group) */}
        {selectedPlanet && (
          <Link
            to={`/worlds/${worldName}/globe/${selectedPlanet}${globeQS}`}
            className="px-3 py-1 text-sm rounded-lg bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors"
            title={t('title.globe')}
          >
            🌐 3D
          </Link>
        )}

        {/* Projection selector */}
        <select
          value={projection}
          onChange={(e) => setProjection(e.target.value as ProjectionType)}
          className="px-2 py-1 rounded bg-space-surface text-sm text-gray-300 border border-space-border"
        >
          {PROJECTION_HELP.map((p) => (
            <option key={p.id} value={p.id}>{t(p.label)}</option>
          ))}
        </select>

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
                    text: t('msg.geographyRasterSavedDetail', { format: r.source_format ?? '' }),
                  }
                : { ok: false, text: t('msg.uploadFailed', { detail: r.detail ?? t('msg.unknownError') }) }
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
                {mapPlanets?.includes(p.id) ? '' : ` (${t('label.noMap')})`}
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

        {/* Help button — opens HelpPage in new tab so users can reference docs
             without leaving their map view. */}
        <a
          href="/help#map-controls"
          target="_blank"
          rel="noopener noreferrer"
          className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold border bg-space-surface text-gray-400 border-space-border hover:text-neon-cyan hover:border-neon-cyan/30 transition-colors"
          title={t('control.helpButton')}
        >
          ?
        </a>

      </div>

      {/* Error banner */}
      {worldPlanetsError && (
        <div className="bg-red-900/20 border-b border-red-700/30 px-4 py-2 text-sm text-red-300 text-center">
          {t('label.dataLoadFailed')}
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
            {localElevation ? (
              <>
                <div className="flex-1 min-h-0">
                  <MapViewer
                    metadata={meta}
                    elevation={localElevation}
                    voronoiCells={voronoiCells}
                    cvtMesh={cvtMesh}
                    layers={layerState.layers}
                    riverFeatures={riverFeatures}
                    projection={projection}

                    onCursorMove={setCursor}
                    onCellHover={handleCellHover}
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
                <MobileCellCard
                  cell={selectedCells.size === 1 ? selectedCellData : null}
                  cursor={cursor}
                  onClose={() => setSelectedCells(new Set())}
                />
              </>
            ) : (
              <div className="flex-1 flex items-center justify-center">
                <div className="text-center text-gray-400">
                  <div className="relative inline-block w-16 h-16 mb-3">
                    <div className="absolute inset-0 rounded-full border border-gray-600 animate-ping opacity-30" />
                    <div className="absolute inset-0 rounded-full border border-neon-cyan/40 animate-pulse" />
                    <div className="absolute inset-3 rounded-full bg-neon-cyan/10 flex items-center justify-center">
                      <div className="w-2 h-2 rounded-full bg-neon-cyan/60 animate-pulse" />
                    </div>
                  </div>
                  <div className="text-sm">{t('label.mapDataLoading')}</div>
                </div>
              </div>
            )}
          </div>

          {/* Floating toggle button (mobile only, visible when drawer closed) */}
          {!leftPanelOpen && (
            <button
              onClick={() => setLeftPanelOpen(true)}
              className="absolute bottom-4 left-4 z-30 w-10 h-10 rounded-full bg-space-panel border border-space-border flex items-center justify-center text-gray-400 hover:text-neon-cyan hover:border-neon-cyan/40 shadow-lg"
              title={t('label.layerSettings')}
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
                    {t('label.layerSettings')}
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
                    {t('msg.noPlateData')}
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
                {t('msg.noPlateData')}
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
            {localElevation ? (
              <>
                <div className="flex-1 min-h-0">
                  <MapViewer
                    metadata={meta}
                    elevation={localElevation}
                    voronoiCells={voronoiCells}
                    cvtMesh={cvtMesh}
                    layers={layerState.layers}
                    riverFeatures={riverFeatures}
                    projection={projection}

                    onCursorMove={setCursor}
                    onCellHover={handleCellHover}
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
            ) : (
              <div className="flex-1 flex items-center justify-center">
                <div className="text-center text-gray-400">
                  <div className="relative inline-block w-16 h-16 mb-3">
                    <div className="absolute inset-0 rounded-full border border-gray-600 animate-ping opacity-30" />
                    <div className="absolute inset-0 rounded-full border border-neon-cyan/40 animate-pulse" />
                    <div className="absolute inset-3 rounded-full bg-neon-cyan/10 flex items-center justify-center">
                      <div className="w-2 h-2 rounded-full bg-neon-cyan/60 animate-pulse" />
                    </div>
                  </div>
                  <div className="text-sm">{t('label.mapDataLoading')}</div>
                </div>
              </div>
            )}
          </div>

          {/* Right panel: cell inspector + minimap */}
          <div className="w-52 shrink-0 bg-space-panel/50 border-l border-space-border flex flex-col min-h-0">
            {/* Scrollable inspector area */}
            <div className="flex-1 min-h-0 overflow-y-auto p-3">
              <MapCellInspector
                cell={inspectorCell}
                cvtMesh={cvtMesh ?? null}
                planetName={currentPlanetName}
                selectedCells={selectedCellObjects}
              />
              {selectedCells.size > 1 && (
                <p className="text-[10px] text-gray-600 mt-2 text-center">
                  {t('msg.escClearSelection')}
                </p>
              )}
            </div>

            {/* Minimap — pinned at bottom */}
            {localElevation && (
              <div className="shrink-0 border-t border-space-border p-3">
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  {t('label.minimap')}
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

{/* Help is now a standalone page at /help, opened via the ? button above. */}
      </div>
    </div>
  )
}
