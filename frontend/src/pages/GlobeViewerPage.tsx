/**
 * GlobeViewerPage — 3D 球面地形可视化.
 *
 * Route: /worlds/:worldName/globe/:planetId
 *
 * Shares cell interaction, colour modes, sidebar panels, and status bar
 * with the 2D MapViewer.  Layout mirrors MapViewerPage:
 *   left panel (layers) · centre (globe) · right panel (inspector)
 */

import { useParams, useSearchParams, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import * as THREE from 'three'
import { api } from '../api/client'
import GlobeViewer, { type GlobeVertex, type GlobeRegion } from '../viewers/GlobeViewer'
import BranchSelector from '../components/BranchSelector'
import MapStatusBar from '../components/map/MapStatusBar'
import MapLayerPanel, { type LayerState } from '../components/map/MapLayerPanel'
import MapCellInspector, { MobileCellCard } from '../components/map/MapCellInspector'
import SunControl from '../components/map/SunControl'
import { solarDeclinationDeg } from '../viewers/utils/solar'
import useGPUTerrain from '../viewers/map/useGPUTerrain'
import useRafCoalesced from '../viewers/map/useRafCoalesced'
import useCellIdMap from '../viewers/map/useCellIdMap'
import { decodePngToFloat32 } from '../viewers/map/utils/imageCodec'
import { normalisedToMeters } from '../viewers/map/utils/projection'
import { buildCellKDTree, type KDTree3D } from '../components/map/utils/kdtree'
import type { VoronoiCell } from '../viewers/map/types'
import type { CursorInfo } from '../components/map/MapViewer'
import GlobeCurrentArrows from '../components/map/GlobeCurrentArrows'
import GlobeWindArrows from '../components/map/GlobeWindArrows'
import ImportElevationButton, { type ImportElevationResult } from '../components/map/ImportElevationButton'
import GeographyRasterButton from '../components/map/GeographyRasterButton'

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

import { getRandomTip } from '../components/map/helpContent'

export default function GlobeViewerPage() {
  const { worldName, planetId } = useParams<{ worldName: string; planetId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const { t } = useTranslation('map')
  const randomTip = useMemo(() => getRandomTip(t), [t])
  const selectedBranch = searchParams.get('branch') || null

  const setSelectedBranch = (branch: string | null) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (branch) next.set('branch', branch)
      else next.delete('branch')
      return next
    }, { replace: true })
  }

  // --- UI State ---
  const [layerState, setLayerState] = useState<LayerState>({ layers: { terrain: 1, landsea: 0, plates: 0, boundaries: 0, coastlines: 1, koppen: 0, currents: 0, winds: 0, biomes: 0, npp: 0, domesticable: 0, soil: 0, provinces: 0, temperature: 0, precipitation: 0, habitable: 0, agriculture: 0, flow: 0 } })
  const globeProjectRef = useRef<((lon: number, lat: number) => { x: number; y: number; edgeFade: number; zoomScale: number; ex: number; ey: number; nx: number; ny: number } | null) | null>(null)
  const [cursor, setCursor] = useState<CursorInfo | null>(null)
  const [hoveredCellId, setHoveredCellId] = useState<number | null>(null)
  /** Last hovered cell — retained so the inspector doesn't reset on mouse-leave. */
  const [lastCellId, setLastCellId] = useState<number | null>(null)
  const [selectedCells, setSelectedCells] = useState<Set<number>>(new Set())

  // --- Data ---
  const { data: meta, isError: metaError } = useQuery({
    queryKey: ['mapMeta', worldName, planetId, selectedBranch],
    queryFn: () => api.getMapMeta(worldName!, planetId!, selectedBranch),
    enabled: !!worldName && !!planetId,
  })

  // Planets that actually have map data in the current branch (branch overlay
  // + root fallback).  Map IDs differ per branch (e.g. climate-dev stores
  // "planet_earth" while terrain-dev stores "earth"), so after a branch
  // switch the mapId in the URL path may no longer exist — redirect to the
  // branch's first available map instead of showing permanent 404s.
  const { data: mapPlanets } = useQuery({
    queryKey: ['mapPlanets', worldName, selectedBranch],
    queryFn: () => api.listMapPlanets(worldName!, selectedBranch),
    enabled: !!worldName,
  })

  useEffect(() => {
    if (!mapPlanets || !planetId) return
    if (mapPlanets.includes(planetId) || mapPlanets.length === 0) return
    const qs = searchParams.toString()
    navigate(
      `/worlds/${worldName}/globe/${mapPlanets[0]}${qs ? `?${qs}` : ''}`,
      { replace: true },
    )
  }, [mapPlanets, planetId, navigate, worldName, searchParams])

  // Planet definitions (for axial tilt, name, etc.)
  const { data: planets } = useQuery({
    queryKey: ['planets', worldName, selectedBranch],
    queryFn: () => api.getPlanets(worldName!, selectedBranch),
    enabled: !!worldName,
    retry: false,
  })

  const currentPlanet = useMemo(() => {
    if (!planets || !planetId) return null
    return planets.find((p: any) => p.id === planetId) ?? null
  }, [planets, planetId])

  const axialTiltDeg = currentPlanet?.axial_tilt_deg ?? 0

  // --- Sun lighting state (synced to URL: ?sun=&season=, shared with 2D map) ---
  const [sunLongitudeDeg, setSunLongitudeDeg] = useState(() => {
    const v = Number(searchParams.get('sun'))
    return Number.isFinite(v) ? v : 0
  })
  // Season (orbital position): 0° = vernal equinox, 90° = N. summer solstice.
  const [seasonDeg, setSeasonDeg] = useState(() => {
    const v = Number(searchParams.get('season'))
    return Number.isFinite(v) ? v : 0
  })
  const [globeZoom, setGlobeZoom] = useState(1)
  // Day/night lighting toggle — default off; synced to URL ?night=1 (shared with 2D).
  const [dayNightEnabled, setDayNightEnabled] = useState(() => searchParams.get('night') === '1')

  // Write sun/season/night back to the URL so lighting carries across 2D↔3D nav.
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

  // Solar declination (subsolar latitude) varies with season + axial tilt.
  const solarDeclination = solarDeclinationDeg(seasonDeg, axialTiltDeg)

  const elevMin = meta?.elevation_min_m ?? -11000
  const elevMax = meta?.elevation_max_m ?? 9000
  const seaLevel = meta?.sea_level_m ?? 0

  const { data: elevationBlob, isError: elevError } = useQuery({
    queryKey: ['elevationBlob', worldName, planetId, selectedBranch],
    queryFn: () => api.getElevationBlob(worldName!, planetId!, selectedBranch),
    enabled: !!worldName && !!planetId, retry: false,
  })

  const [elevData, setElevData] = useState<Float32Array | null>(null)
  const [elevDims, setElevDims] = useState<{ w: number; h: number }>({ w: 0, h: 0 })

  useEffect(() => {
    if (!elevationBlob) { setElevData(null); return }
    let cancelled = false
    decodePngToFloat32(elevationBlob).then(({ data, width, height }) => {
      if (!cancelled) { setElevData(data); setElevDims({ w: width, h: height }) }
    })
    return () => { cancelled = true }
  }, [elevationBlob])

  // CVT mesh (for plates/boundaries modes + cell lookup)
  const { data: cvtMesh, isError: cvtMeshError } = useQuery({
    queryKey: ['cvtMesh', worldName, planetId, selectedBranch],
    queryFn: () => api.getCvtMesh(worldName!, planetId!, selectedBranch),
    enabled: !!worldName && !!planetId, retry: false,
  })

  const cellIdMap = useCellIdMap({
    cvtMesh: cvtMesh ?? null,
    width: meta?.width ?? 2048,
    height: meta?.height ?? 1024,
  })

  // --- GPU texture ---
  // Opacity sliders fire many events per frame; coalesce so the composite
  // pass (and any data-driven re-bake) runs at most once per animation frame.
  const renderLayers = useRafCoalesced(layerState.layers)

  const { texture: terrainTexture, renderComposite } = useGPUTerrain({
    elevation: elevData,
    width: elevDims.w, height: elevDims.h,
    seaLevel, elevMinM: elevMin, elevMaxM: elevMax,
    layers: renderLayers,
    cvtMesh: cvtMesh ?? null,
    cellIdMap: cellIdMap ?? null,
    flipHorizontal: false,
  })

  // useGPUTerrain returns a 1px placeholder DataTexture before the real
  // terrain bake completes.  Passing it to GlobeViewer would mount the
  // Canvas early (black globe with gridlines), and the later material
  // swap when the 4096px texture arrives would fail (needsUpdate consumed
  // by the placeholder).  Keep the loading UI until the real texture lands.
  const displayTexture = useMemo(() => {
    if (terrainTexture) {
      const w = (terrainTexture.image as any)?.width ?? 0
      if (w <= 1) return null  // placeholder — stay in loading state
      terrainTexture.needsUpdate = true
      // Signal the performance observer that the real texture is ready.
      import('../utils/perf').then(({ mark }) => mark('first-paint-end'))
    }
    return terrainTexture
  }, [terrainTexture])

  // --- KD-tree ---
  const kdTree = useMemo<KDTree3D | null>(() => {
    const cells = cvtMesh?.cells
    if (!cells || cells.length === 0) return null
    return buildCellKDTree(cells as VoronoiCell[])
  }, [cvtMesh])

  const voronoiCells: VoronoiCell[] = useMemo(
    () => (cvtMesh?.cells as VoronoiCell[]) ?? [],
    [cvtMesh],
  )

  // --- Panel state machine (mirrors MapViewerPage) ---
  const selectedCellData = useMemo(() => {
    if (selectedCells.size === 0) return null
    const id = [...selectedCells][0]
    return voronoiCells.find((c) => c.id === id) ?? null
  }, [voronoiCells, selectedCells])

  const hoveredCellData = useMemo(() => {
    if (hoveredCellId === null) return null
    return voronoiCells.find((c) => c.id === hoveredCellId) ?? null
  }, [voronoiCells, hoveredCellId])

  const lastCellData = useMemo(() => {
    if (lastCellId === null) return null
    return voronoiCells.find((c) => c.id === lastCellId) ?? null
  }, [voronoiCells, lastCellId])

  // Inspector shows the last hovered cell (not the live hover), so leaving the
  // globe doesn't reset the panel or lose its open/closed group state.
  const inspectorCell = selectedCells.size === 1
    ? selectedCellData
    : selectedCells.size > 1
      ? null
      : lastCellData

  const selectedCellObjects = useMemo(() => {
    if (selectedCells.size <= 1) return undefined
    return [...selectedCells].map((id) => voronoiCells.find((c) => c.id === id)).filter(Boolean) as VoronoiCell[]
  }, [voronoiCells, selectedCells])

  // --- CVT mesh data for polygon highlights ---
  const globeVertices = useMemo<GlobeVertex[] | undefined>(() => cvtMesh?.vertices, [cvtMesh])
  const globeRegions = useMemo<GlobeRegion[] | undefined>(() => cvtMesh?.regions, [cvtMesh])
  // --- Handlers ---

  const handleCellHover = useCallback((lon: number, lat: number) => {
    const mapW = meta?.width ?? 2048
    const mapH = meta?.height ?? 1024
    const px = Math.round(((lon + 180) / 360) * (mapW - 1))
    const py = Math.round(((90 - lat) / 180) * (mapH - 1))
    const elev = elevData
      ? (elevData?.[Math.max(0, Math.min(mapH - 1, py)) * mapW + Math.max(0, Math.min(mapW - 1, px))] ?? 0)
      : 0

    if (kdTree) {
      const rad = THREE.MathUtils.degToRad(lat)
      const cosLat = Math.cos(rad)
      const cellId = kdTree.nearest(
        cosLat * Math.cos(THREE.MathUtils.degToRad(lon)),
        Math.sin(rad),
        cosLat * Math.sin(THREE.MathUtils.degToRad(lon)),
      )
      setHoveredCellId(cellId >= 0 ? cellId : null)
      if (cellId >= 0) setLastCellId(cellId)

      // Use CVT mesh elevation directly — same source as the right panel
      const meshElev = cellId >= 0 ? voronoiCells[cellId]?.elevation : undefined
      setCursor({
        lon: Math.round(lon * 100) / 100,
        lat: Math.round(lat * 100) / 100,
        elevation: meshElev ?? elev,
        elevationM: meshElev != null ? Math.round(meshElev) : Math.round(normalisedToMeters(elev, elevMin, elevMax)),
        pixelX: px,
        pixelY: py,
      })
    } else {
      setHoveredCellId(null)
      setCursor({
        lon: Math.round(lon * 100) / 100,
        lat: Math.round(lat * 100) / 100,
        elevation: elev,
        elevationM: Math.round(normalisedToMeters(elev, elevMin, elevMax)),
        pixelX: px,
        pixelY: py,
      })
    }
  }, [elevData, meta, elevMin, elevMax, kdTree, voronoiCells])

  const handleCellClick = useCallback((lon: number, lat: number, ctrlKey: boolean) => {
    if (!kdTree) return
    const rad = THREE.MathUtils.degToRad(lat)
    const cosLat = Math.cos(rad)
    const cellId = kdTree.nearest(
      cosLat * Math.cos(THREE.MathUtils.degToRad(lon)),
      Math.sin(rad),
      cosLat * Math.sin(THREE.MathUtils.degToRad(lon)),
    )
    if (cellId < 0) return
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
      if (alreadySelected && prev.size === 1) return new Set()
      return new Set([cellId])
    })
  }, [kdTree])

  // Esc → clear all selections
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedCells(new Set())
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // --- URLs ---
  const branchQS = selectedBranch ? `?branch=${encodeURIComponent(selectedBranch)}` : ''
  const stellarQS = `${branchQS}${branchQS ? '&' : '?'}focus=${encodeURIComponent(planetId!)}`
  // Forward current lighting (sun/season) + branch when switching to the 2D map.
  const mapQS = searchParams.toString() ? `?${searchParams.toString()}` : ''
  const handleTransition = useCallback(() => {
    navigate(`/worlds/${worldName}/viewer3d${stellarQS}`)
  }, [navigate, worldName, stellarQS])

  // --- Mobile panel state ---
  const [leftPanelOpen, setLeftPanelOpen] = useState(false)
  const [importMsg, setImportMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const handleImported = useCallback(
    (r: ImportElevationResult) => {
      setImportMsg(r.ok
        ? { ok: true, text: t('msg.heightmapImported') }
        : { ok: false, text: t('msg.importFailed', { detail: r.detail ?? t('msg.unknownError') }) },
      )
    },
    [],
  )

  // --- Render ---
  if (!worldName || !planetId) {
    return <div className="flex items-center justify-center h-full text-gray-500">{t('status.noWorldOrPlanet')}</div>
  }

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      {/* Top bar */}
      <div className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2 bg-space-panel border-b border-space-border shrink-0">
        <Link to={`/worlds/${worldName}`}
          className="text-gray-400 hover:text-neon-cyan transition-colors text-sm">{t('action.back')}</Link>
        <h1 className="text-base sm:text-lg font-bold text-neon-cyan neon-glow-subtle">{t('title.globe')}</h1>
        <span className="text-[10px] sm:text-xs text-gray-600 font-mono hidden sm:inline">{currentPlanet?.name ?? planetId}</span>
        <div className="flex-1" />
        <Link to={`/worlds/${worldName}/map/${planetId}${mapQS}`}
          className="px-2 sm:px-3 py-1 text-xs sm:text-sm rounded-lg bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors"
          title={t('label.switchTo2D')}>
          🗺️ 2D
        </Link>
        <Link to={`/worlds/${worldName}/viewer3d${stellarQS}`}
          className="px-2 sm:px-3 py-1 text-xs sm:text-sm rounded-lg bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors"
          title={t('label.switchToStellar')}>
          🔭 {t('label.stellarShort')}
        </Link>

        {/* Import elevation (same position as 2D toolbar) */}
        {planetId && (
          <ImportElevationButton
            worldName={worldName!}
            planetId={planetId}
            branch={selectedBranch}
            onImported={handleImported}
          />
        )}
        {/* Upload geography raster */}
        <GeographyRasterButton
          worldName={worldName!}
          branch={selectedBranch}
          onUploaded={(r) =>
            setImportMsg(
              r.ok
                ? { ok: true, text: t('msg.geographyRasterSaved') }
                : { ok: false, text: t('msg.uploadFailed', { detail: r.detail ?? t('msg.unknownError') }) },
            )
          }
        />

        {/* Planet selector */}
        {planets && planets.length > 0 && (
          <select
            value={planetId}
            onChange={(e) => {
              const qs = searchParams.toString()
              navigate(`/worlds/${worldName}/globe/${e.target.value}${qs ? `?${qs}` : ''}`)
            }}
            className="px-2 py-1 rounded bg-space-surface text-sm text-gray-300 border border-space-border"
          >
            {planets.map((p: any) => (
              <option key={p.id} value={p.id}>
                {p.name ?? p.id}
                {mapPlanets?.includes(p.id) ? '' : ` (${t('label.noMap')})`}
              </option>
            ))}
          </select>
        )}

        <BranchSelector worldName={worldName} selectedBranch={selectedBranch} onSelect={setSelectedBranch} />

        {/* Help button — opens HelpPage in new tab */}
        <a
          href="/help#globe-viewer"
          target="_blank"
          rel="noopener noreferrer"
          className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold border bg-space-surface text-gray-400 border-space-border hover:text-neon-cyan hover:border-neon-cyan/30 transition-colors"
          title={t('control.helpButton')}
        >
          ?
        </a>
      </div>

      {/* Error / info banner */}
      {importMsg && (
        <div className={`border-b px-4 py-2 text-sm text-center ${
          importMsg.ok ? 'bg-green-900/20 border-green-700/30 text-green-300' : 'bg-red-900/20 border-red-700/30 text-red-300'
        }`}>
          {importMsg.text}
        </div>
      )}
      {(metaError || elevError || cvtMeshError) && (
        <div className="bg-red-900/20 border-b border-red-700/30 px-4 py-2 text-sm text-red-300 text-center">
          {t('label.dataLoadFailed')}
        </div>
      )}

      {/* Main content */}
      <div className="flex-1 min-h-0 relative">
        {/* === Mobile layout (visible only < md) === */}
        <div className="flex flex-col min-h-0 md:hidden absolute inset-0">
          <div className="flex-1 flex flex-col min-h-0">
            <div className="flex-1 min-h-0 relative">
              {!displayTexture ? (
                <div className="absolute inset-0 flex items-center justify-center z-20">
                  <div className="text-center text-gray-400">
                    <div className="relative inline-block w-20 h-20 mb-4">
                      <div className="absolute inset-0 rounded-full border border-gray-600 animate-ping opacity-30" />
                      <div className="absolute inset-0 rounded-full border border-neon-cyan/40 animate-pulse" />
                      <div className="absolute inset-4 rounded-full bg-neon-cyan/10 flex items-center justify-center">
                        <div className="w-3 h-3 rounded-full bg-neon-cyan/60 animate-pulse" />
                      </div>
                    </div>
                    <div className="text-sm">
                      {elevError
                        ? t('label.noMapData')
                        : elevationBlob && !elevData ? t('label.decodingHeightmap')
                        : elevationBlob && elevData ? t('label.generatingTexture')
                        : t('label.mapDataLoading')}
                    </div>
                    <div className="mt-3 text-xs text-gray-600 max-w-xs mx-auto leading-relaxed">
                      {randomTip}
                    </div>
                  </div>
                </div>
            ) : (
              <GlobeViewer
                texture={displayTexture}
                renderComposite={renderComposite}
                onTransition={handleTransition}
                onCellHover={handleCellHover}
                onCellClick={handleCellClick}
                onHoverOut={() => { setHoveredCellId(null); setCursor(null) }}
                onDistanceChange={setGlobeZoom}
                vertices={globeVertices}
                regions={globeRegions}
                hoveredCellId={hoveredCellId}
                selectedCellIds={selectedCells}
                sunLongitudeDeg={sunLongitudeDeg}
                solarDeclinationDeg={solarDeclination}
                dayNight={dayNightEnabled}
                globeProjectRef={globeProjectRef}
              />
            )}
            <GlobeCurrentArrows
              projectRef={globeProjectRef}
              voronoiCells={voronoiCells}
              currentOpacity={layerState.layers.currents ?? 0}
            />
            <GlobeWindArrows
              projectRef={globeProjectRef}
              voronoiCells={voronoiCells}
              windOpacity={layerState.layers.winds ?? 0}
            />
          </div>
          <MobileCellCard
            cell={selectedCells.size === 1 ? selectedCellData : null}
            cursor={cursor}
            onClose={() => setSelectedCells(new Set())}
          />
        </div>

        {/* Floating toggle (mobile only) */}
        {!leftPanelOpen && (
          <button
            onClick={() => setLeftPanelOpen(true)}
            className="absolute bottom-4 left-4 z-30 w-10 h-10 rounded-full bg-space-panel border border-space-border flex items-center justify-center text-gray-400 hover:text-neon-cyan hover:border-neon-cyan/40 shadow-lg"
            title={t('label.layerSettings')}
          >
            ☰
          </button>
        )}

        {/* Left panel drawer overlay (mobile only) */}
        {leftPanelOpen && (
          <>
            <div className="absolute inset-0 bg-black/50 z-40" onClick={() => setLeftPanelOpen(false)} />
            <div className="absolute left-0 top-0 bottom-0 w-64 bg-space-panel z-50 overflow-y-auto p-3 space-y-4 shadow-xl">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{t('label.layerSettings')}</span>
                <button onClick={() => setLeftPanelOpen(false)} className="text-gray-500 hover:text-gray-300 text-lg leading-none">✕</button>
              </div>
              <MapLayerPanel state={layerState} onChange={setLayerState} />
              <div className="mt-3 pt-3 border-t border-space-border">
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

        {/* === Desktop layout (≥ md) === */}
        <div className="hidden md:flex absolute inset-0">
          {/* Left panel: layers */}
          <div className="w-56 shrink-0 bg-space-panel/50 border-r border-space-border overflow-y-auto p-3">
            <MapLayerPanel state={layerState} onChange={setLayerState} />
            <div className="mt-3 pt-3 border-t border-space-border">
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

      {/* Centre: globe */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex-1 min-h-0 relative">
          {!displayTexture ? (
            <div className="absolute inset-0 flex items-center justify-center z-20">
              <div className="text-center text-gray-400">
                <div className="relative inline-block w-20 h-20 mb-4">
                  <div className="absolute inset-0 rounded-full border border-gray-600 animate-ping opacity-30" />
                  <div className="absolute inset-0 rounded-full border border-neon-cyan/40 animate-pulse" />
                  <div className="absolute inset-4 rounded-full bg-neon-cyan/10 flex items-center justify-center">
                    <div className="w-3 h-3 rounded-full bg-neon-cyan/60 animate-pulse" />
                  </div>
                </div>
                <div className="text-sm">
                  {elevError
                    ? t('label.noMapData')
                    : elevationBlob && !elevData ? t('label.decodingHeightmap')
                    : elevationBlob && elevData ? t('label.generatingTexture')
                    : t('label.mapDataLoading')}
                </div>
                <div className="mt-3 text-xs text-gray-600 max-w-xs mx-auto leading-relaxed">
                  {randomTip}
                </div>
              </div>
            </div>
          ) : (
            <GlobeViewer
              texture={displayTexture}
              renderComposite={renderComposite}
              onTransition={handleTransition}
              onCellHover={handleCellHover}
              onCellClick={handleCellClick}
              onHoverOut={() => { setHoveredCellId(null); setCursor(null) }}
              onDistanceChange={setGlobeZoom}
              vertices={globeVertices}
              regions={globeRegions}
              hoveredCellId={hoveredCellId}
              selectedCellIds={selectedCells}
              sunLongitudeDeg={sunLongitudeDeg}
              solarDeclinationDeg={solarDeclination}
              dayNight={dayNightEnabled}
              globeProjectRef={globeProjectRef}
            />
          )}
          <GlobeCurrentArrows
            projectRef={globeProjectRef}
            voronoiCells={voronoiCells}
            currentOpacity={layerState.layers.currents ?? 0}
          />
          <GlobeWindArrows
            projectRef={globeProjectRef}
            voronoiCells={voronoiCells}
            windOpacity={layerState.layers.winds ?? 0}
          />
        </div>
        <MapStatusBar cursor={cursor} zoom={globeZoom} hoveredCell={hoveredCellData} />
      </div>

      {/* Right panel: cell inspector */}
      <div className="w-52 shrink-0 bg-space-panel/50 border-l border-space-border overflow-y-auto p-3">
        <MapCellInspector
          cell={inspectorCell}
          cvtMesh={cvtMesh ?? null}
          planetName={currentPlanet?.name ?? planetId}
          selectedCells={selectedCellObjects}
        />
      </div>
    </div>

{/* Help is now a standalone page at /help, opened via the ? button above. */}
  </div>
  </div>
)
}
