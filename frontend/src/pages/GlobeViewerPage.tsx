/**
 * GlobeViewerPage — 3D 球面地形可视化.
 *
 * Route: /worlds/:worldName/globe/:planetId
 *
 * Shared posture (layers / branch / lighting / monthly climate / cell
 * selection) lives in usePlanetViewState — this page adds the 3D renderer
 * (R3F sphere + orbit controls + spin + stellar transition) and the 3D
 * wind/current arrow overlays.  Layout mirrors MapViewerPage:
 *   left panel (layers) · centre (globe) · right panel (inspector)
 */

import { useParams, useSearchParams, Link, useNavigate } from 'react-router-dom'
import { useState, useMemo, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import * as THREE from 'three'
import GlobeViewer, { type GlobeVertex, type GlobeRegion } from '../viewers/GlobeViewer'
import BranchSelector from '../components/BranchSelector'
import MapStatusBar from '../components/map/MapStatusBar'
import MapLayerPanel from '../components/map/MapLayerPanel'
import MapCellInspector, { MobileCellCard } from '../components/map/MapCellInspector'
import SunControl from '../components/map/SunControl'
import TimeControl from '../components/map/TimeControl'
import useGPUTerrain from '../viewers/map/useGPUTerrain'
import useRafCoalesced from '../viewers/map/useRafCoalesced'
import { buildCellKDTree, type KDTree3D } from '../components/map/utils/kdtree'
import type { VoronoiCell } from '../viewers/map/types'
import { normalisedToMeters } from '../viewers/map/utils/mapCoords'
import GlobeCurrentArrows from '../components/map/GlobeCurrentArrows'
import GlobeWindArrows from '../components/map/GlobeWindArrows'
import ImportElevationButton from '../components/map/ImportElevationButton'
import GeographyRasterButton from '../components/map/GeographyRasterButton'
import { usePlanetViewState } from '../viewers/map/usePlanetViewState'

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

import { getRandomTip } from '../components/map/helpContent'

export default function GlobeViewerPage() {
  const { worldName, planetId } = useParams<{ worldName: string; planetId?: string }>()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { t } = useTranslation('map')
  const randomTip = useMemo(() => getRandomTip(t), [t])

  const vs = usePlanetViewState(worldName, planetId, 'globe')
  const {
    selectedBranch, setSelectedBranch,
    cleanMode, setCleanMode,
    timelapsePlaying, setTimelapsePlaying, monthMs, setMonthMs,
    sunSweep, setSunSweep,
    layerState, setLayerState,
    monthlyMode, handleMonthlyModeChange, monthlyField,
    sunLongitudeDeg, setSunLongitudeDeg, seasonDeg, setSeasonDeg,
    dayNightEnabled, setDayNightEnabled, solarDeclination, axialTiltDeg,
    selectedPlanet, mapPlanets, meta, metaError, elevError, cvtMeshError,
    bodyByName,
    elevation, elevationDims, cvtMesh, voronoiCells, cellIdMap,
    monthlyThematic, monthlyData, monthlyMonth, yearlyData, uccTexture,
    cursor, setCursor, handleCellHover, selectedCells,
    selectCell, clearSelection,
    hoveredCell, hoveredCellData, inspectorCell, selectedCellData, selectedCellObjects,
    importMsg, setImportMsg, handleImported,
  } = vs

  // Auto spin (?spin=1): slow continuous orbit for recording.  Independent of
  // clean mode so ?clean=1&spin=1 is the standard recording posture.
  const autoSpin = searchParams.get('spin') === '1'
  const setAutoSpin = (v: boolean) => {
    // The URL is the source of truth; navigate with the param toggled.
    const next = new URLSearchParams(searchParams)
    if (v) next.set('spin', '1')
    else next.delete('spin')
    navigate(`?${next.toString()}`, { replace: true })
  }

  // Stable empty set — clean mode suppresses hover/selection highlights without
  // changing cell-picking state underneath.
  const emptySelection = useMemo(() => new Set<number>(), [])

  const globeProjectRef = useRef<((lon: number, lat: number) => { x: number; y: number; edgeFade: number; zoomScale: number; ex: number; ey: number; nx: number; ny: number } | null) | null>(null)
  const [globeZoom, setGlobeZoom] = useState(1)

  const elevMin = meta?.elevation_min_m ?? -11000
  const elevMax = meta?.elevation_max_m ?? 9000
  const seaLevel = meta?.sea_level_m ?? 0

  // --- GPU texture ---
  // Opacity sliders fire many events per frame; coalesce so the composite
  // pass (and any data-driven re-bake) runs at most once per animation frame.
  const renderLayers = useRafCoalesced(layerState.layers)

  const { texture: terrainTexture, renderComposite } = useGPUTerrain({
    elevation,
    width: elevationDims.w, height: elevationDims.h,
    seaLevel, elevMinM: elevMin, elevMaxM: elevMax,
    layers: renderLayers,
    cvtMesh,
    cellIdMap,
    monthlyTemperature: monthlyField === 'temperature' ? monthlyThematic : null,
    monthlyPrecipitation: monthlyField === 'precipitation' ? monthlyThematic : null,
    monthlyPressure: monthlyField === 'pressure' ? monthlyThematic : null,
    monthlyPressureError: monthlyField === 'pressureError' ? monthlyThematic : null,
    monthlySlp: monthlyField === 'slp' ? monthlyThematic : null,
    uccTexture,
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

  // --- CVT mesh data for polygon highlights ---
  const globeVertices = useMemo<GlobeVertex[] | undefined>(() => cvtMesh?.vertices, [cvtMesh])
  const globeRegions = useMemo<GlobeRegion[] | undefined>(() => cvtMesh?.regions, [cvtMesh])
  // --- Handlers ---

  const handleCellHoverLonLat = useCallback((lon: number, lat: number) => {
    const mapW = meta?.width ?? 2048
    const mapH = meta?.height ?? 1024
    const px = Math.round(((lon + 180) / 360) * (mapW - 1))
    const py = Math.round(((90 - lat) / 180) * (mapH - 1))
    const elev = elevation
      ? (elevation?.[Math.max(0, Math.min(mapH - 1, py)) * mapW + Math.max(0, Math.min(mapW - 1, px))] ?? 0)
      : 0

    if (kdTree) {
      const rad = THREE.MathUtils.degToRad(lat)
      const cosLat = Math.cos(rad)
      const cellId = kdTree.nearest(
        cosLat * Math.cos(THREE.MathUtils.degToRad(lon)),
        Math.sin(rad),
        cosLat * Math.sin(THREE.MathUtils.degToRad(lon)),
      )
      handleCellHover(cellId >= 0 ? cellId : null)

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
      handleCellHover(null)
      setCursor({
        lon: Math.round(lon * 100) / 100,
        lat: Math.round(lat * 100) / 100,
        elevation: elev,
        elevationM: Math.round(normalisedToMeters(elev, elevMin, elevMax)),
        pixelX: px,
        pixelY: py,
      })
    }
  }, [elevation, meta, elevMin, elevMax, kdTree, voronoiCells, handleCellHover, setCursor])

  const handleCellClickLonLat = useCallback((lon: number, lat: number, ctrlKey: boolean) => {
    if (!kdTree) return
    const rad = THREE.MathUtils.degToRad(lat)
    const cosLat = Math.cos(rad)
    const cellId = kdTree.nearest(
      cosLat * Math.cos(THREE.MathUtils.degToRad(lon)),
      Math.sin(rad),
      cosLat * Math.sin(THREE.MathUtils.degToRad(lon)),
    )
    if (cellId < 0) return
    selectCell(cellId, ctrlKey)
  }, [kdTree, selectCell])

  // --- URLs ---
  const branchQS = selectedBranch ? `?branch=${encodeURIComponent(selectedBranch)}` : ''
  const stellarQS = `${branchQS}${branchQS ? '&' : '?'}focus=${encodeURIComponent(selectedPlanet)}`
  // Forward current lighting (sun/season) + branch when switching to the 2D map.
  const mapQS = searchParams.toString() ? `?${searchParams.toString()}` : ''
  const handleTransition = useCallback(() => {
    navigate(`/worlds/${worldName}/viewer3d${stellarQS}`)
  }, [navigate, worldName, stellarQS])

  // --- Mobile panel state ---
  const [leftPanelOpen, setLeftPanelOpen] = useState(false)

  // --- Render ---
  if (!worldName) {
    return <div className="flex items-center justify-center h-full text-gray-500">{t('status.noWorldOrPlanet')}</div>
  }

  const currentPlanet = selectedPlanet ? bodyByName.get(selectedPlanet) : undefined

  return (
    <div className={cleanMode
      ? 'fixed inset-0 z-40 flex flex-col bg-[#030308]'
      : 'flex flex-col h-[calc(100vh-56px)] md:h-screen'}>
      {/* Top bar */}
      {!cleanMode && (
      <div className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2 bg-space-panel border-b border-space-border shrink-0">
        <Link to={`/worlds/${worldName}`}
          className="text-gray-400 hover:text-neon-cyan transition-colors text-sm">{t('action.back')}</Link>
        <h1 className="text-base sm:text-lg font-bold text-neon-cyan neon-glow-subtle">{t('title.globe')}</h1>
        <span className="text-[10px] sm:text-xs text-gray-600 font-mono hidden sm:inline">{currentPlanet?.name ?? selectedPlanet}</span>
        <div className="flex-1" />
        <Link to={`/worlds/${worldName}/map/${selectedPlanet}${mapQS}`}
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
        {selectedPlanet && (
          <ImportElevationButton
            worldName={worldName!}
            planetId={selectedPlanet}
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

        {/* Body selector — every body with map data; display names resolved
            from the astronomy catalogs (planets + stellar bodies) */}
        {mapPlanets && mapPlanets.length > 0 && (
          <select
            value={selectedPlanet}
            onChange={(e) => {
              const qs = searchParams.toString()
              navigate(`/worlds/${worldName}/globe/${e.target.value}${qs ? `?${qs}` : ''}`)
            }}
            className="px-2 py-1 rounded bg-space-surface text-sm text-gray-300 border border-space-border"
          >
            {mapPlanets.map((id: string) => (
              <option key={id} value={id}>
                {bodyByName.get(id)?.name ?? id}
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
      )}

      {/* Error / info banner */}
      {!cleanMode && importMsg && (
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
                        : elevation && elevationDims.w === 0 ? t('label.decodingHeightmap')
                        : elevation ? t('label.generatingTexture')
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
                onCellHover={handleCellHoverLonLat}
                onCellClick={handleCellClickLonLat}
                onHoverOut={() => { handleCellHover(null); setCursor(null) }}
                onDistanceChange={setGlobeZoom}
                vertices={globeVertices}
                regions={globeRegions}
                hoveredCellId={cleanMode ? null : hoveredCell}
                selectedCellIds={cleanMode ? emptySelection : selectedCells}
                sunLongitudeDeg={sunLongitudeDeg}
                solarDeclinationDeg={solarDeclination}
                dayNight={dayNightEnabled}
                autoSpin={autoSpin}
                chrome={!cleanMode}
                interactive={!cleanMode}
                frameless={cleanMode}
                globeProjectRef={globeProjectRef}
              />
            )}
            <GlobeCurrentArrows
              projectRef={globeProjectRef}
              voronoiCells={voronoiCells}
              currentOpacity={layerState.layers.currents ?? 0}
            />
            <GlobeCurrentArrows
              projectRef={globeProjectRef}
              voronoiCells={voronoiCells}
              currentOpacity={layerState.layers.currentError ?? 0}
              deviation
            />
            <GlobeWindArrows
              projectRef={globeProjectRef}
              voronoiCells={voronoiCells}
              windOpacity={layerState.layers.winds ?? 0}
              monthlyWindEast={monthlyMode ? monthlyData?.windEastMonthly ?? null : null}
              monthlyWindNorth={monthlyMode ? monthlyData?.windNorthMonthly ?? null : null}
              month={monthlyMonth}
            />
            <GlobeWindArrows
              projectRef={globeProjectRef}
              voronoiCells={voronoiCells}
              windOpacity={layerState.layers.windError ?? 0}
              deviation
            />
          </div>
          {!cleanMode && (
            <MobileCellCard
              cell={selectedCells.size === 1 ? selectedCellData : null}
              cursor={cursor}
              onClose={clearSelection}
            />
          )}
        </div>

        {/* Floating toggle (mobile only) */}
        {!cleanMode && !leftPanelOpen && (
          <button
            onClick={() => setLeftPanelOpen(true)}
            className="absolute bottom-4 left-4 z-30 w-10 h-10 rounded-full bg-space-panel border border-space-border flex items-center justify-center text-gray-400 hover:text-neon-cyan hover:border-neon-cyan/40 shadow-lg"
            title={t('label.layerSettings')}
          >
            ☰
          </button>
        )}

        {/* Left panel drawer overlay (mobile only) */}
        {!cleanMode && leftPanelOpen && (
          <>
            <div className="absolute inset-0 bg-black/50 z-40" onClick={() => setLeftPanelOpen(false)} />
            <div className="absolute left-0 top-0 bottom-0 w-64 bg-space-panel z-50 overflow-y-auto p-3 space-y-4 shadow-xl">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{t('label.layerSettings')}</span>
                <button onClick={() => setLeftPanelOpen(false)} className="text-gray-500 hover:text-gray-300 text-lg leading-none">✕</button>
              </div>
              <TimeControl
                monthlyMode={monthlyMode}
                onMonthlyModeChange={handleMonthlyModeChange}
                seasonDeg={seasonDeg}
                onSeasonChange={setSeasonDeg}
                axialTiltDeg={axialTiltDeg}
                playing={timelapsePlaying}
                onPlayingChange={setTimelapsePlaying}
                monthMs={monthMs}
                onMonthMsChange={setMonthMs}
                sunSweep={sunSweep}
                onSunSweepChange={setSunSweep}
              />
              <MapLayerPanel
                state={layerState}
                onChange={setLayerState}
                isEarth={worldName === 'earth'}
                monthlyMode={monthlyMode}
                monthIndex={monthlyMonth}
                onMonthlyModeChange={handleMonthlyModeChange}
              />
              <div className="mt-3 pt-3 border-t border-space-border">
                <SunControl
                  sunLongitudeDeg={sunLongitudeDeg}
                  onLongitudeChange={setSunLongitudeDeg}
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
          {!cleanMode && (
          <div className="w-56 shrink-0 bg-space-panel/50 border-r border-space-border overflow-y-auto p-3 space-y-4">
            <TimeControl
              monthlyMode={monthlyMode}
              onMonthlyModeChange={handleMonthlyModeChange}
              seasonDeg={seasonDeg}
              onSeasonChange={setSeasonDeg}
              axialTiltDeg={axialTiltDeg}
              playing={timelapsePlaying}
              onPlayingChange={setTimelapsePlaying}
              monthMs={monthMs}
              onMonthMsChange={setMonthMs}
              sunSweep={sunSweep}
              onSunSweepChange={setSunSweep}
            />
            <MapLayerPanel
              state={layerState}
              onChange={setLayerState}
              isEarth={worldName === 'earth'}
              monthlyMode={monthlyMode}
              monthIndex={monthlyMonth}
              onMonthlyModeChange={handleMonthlyModeChange}
            />
            <div className="mt-3 pt-3 border-t border-space-border">
              <SunControl
                  sunLongitudeDeg={sunLongitudeDeg}
                  onLongitudeChange={setSunLongitudeDeg}
                  enabled={dayNightEnabled}
                  onEnabledChange={setDayNightEnabled}
                />
            </div>
          </div>
          )}

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
                    : elevation && elevationDims.w === 0 ? t('label.decodingHeightmap')
                    : elevation ? t('label.generatingTexture')
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
              onCellHover={handleCellHoverLonLat}
              onCellClick={handleCellClickLonLat}
              onHoverOut={() => { handleCellHover(null); setCursor(null) }}
              onDistanceChange={setGlobeZoom}
              vertices={globeVertices}
              regions={globeRegions}
              hoveredCellId={cleanMode ? null : hoveredCell}
              selectedCellIds={cleanMode ? emptySelection : selectedCells}
              sunLongitudeDeg={sunLongitudeDeg}
              solarDeclinationDeg={solarDeclination}
              dayNight={dayNightEnabled}
              autoSpin={autoSpin}
              chrome={!cleanMode}
              interactive={!cleanMode}
              frameless={cleanMode}
              globeProjectRef={globeProjectRef}
            />
          )}
          <GlobeCurrentArrows
            projectRef={globeProjectRef}
            voronoiCells={voronoiCells}
            currentOpacity={layerState.layers.currents ?? 0}
          />
          <GlobeCurrentArrows
            projectRef={globeProjectRef}
            voronoiCells={voronoiCells}
            currentOpacity={layerState.layers.currentError ?? 0}
            deviation
          />
          <GlobeWindArrows
            projectRef={globeProjectRef}
            voronoiCells={voronoiCells}
            windOpacity={layerState.layers.winds ?? 0}
            monthlyWindEast={monthlyMode ? monthlyData?.windEastMonthly ?? null : null}
            monthlyWindNorth={monthlyMode ? monthlyData?.windNorthMonthly ?? null : null}
            month={monthlyMonth}
          />
          <GlobeWindArrows
            projectRef={globeProjectRef}
            voronoiCells={voronoiCells}
            windOpacity={layerState.layers.windError ?? 0}
            deviation
          />

          {/* Recording controls — float in the globe view's bottom-right corner
              (the view area has spare room; the top bar is already crowded).
              Fully hidden in clean mode: the mouse is not controllable during a
              recording, so even hover-only buttons would pollute the frame. */}
          {!cleanMode && (
          <div className="absolute bottom-3 right-3 z-30 flex items-center gap-2">
            <button
              onClick={() => setAutoSpin(!autoSpin)}
              className={`w-9 h-9 rounded-full flex items-center justify-center text-sm border shadow-lg transition-colors ${
                autoSpin
                  ? 'bg-neon-cyan/20 text-neon-cyan border-neon-cyan/40'
                  : 'bg-space-panel/80 text-gray-400 border-space-border hover:text-neon-cyan hover:border-neon-cyan/40'
              }`}
              title={t('label.autoSpin')}
            >
              ↻
            </button>
            <button
              onClick={() => setCleanMode(true)}
              className="w-9 h-9 rounded-full flex items-center justify-center text-sm border bg-space-panel/80 text-gray-400 border-space-border hover:text-neon-cyan hover:border-neon-cyan/40 shadow-lg transition-colors"
              title={t('label.cleanMode')}
            >
              ⛶
            </button>
          </div>
          )}
        </div>
        {!cleanMode && (
          <MapStatusBar cursor={cursor} zoom={globeZoom} hoveredCell={hoveredCellData} />
        )}
      </div>

      {/* Right panel: cell inspector */}
      {!cleanMode && (
      <div className="w-52 shrink-0 bg-space-panel/50 border-l border-space-border overflow-y-auto p-3">
        <MapCellInspector
          cell={inspectorCell}
          cvtMesh={cvtMesh}
          planetName={currentPlanet?.name ?? selectedPlanet}
          selectedCells={selectedCellObjects}
          activeColorMode={vs.activeColorMode}
          monthlyMode={monthlyMode}
          monthIndex={monthlyMonth}
          monthlyData={monthlyData}
          yearlyData={yearlyData}
          isEarth={worldName === 'earth'}
        />
      </div>
      )}
    </div>

{/* Help is now a standalone page at /help, opened via the ? button above. */}
  </div>

  {/* Clean-mode exit — invisible until hovered, so it never pollutes a recording */}
  {cleanMode && (
    <button
      onClick={() => setCleanMode(false)}
      className="absolute top-2 right-2 z-50 w-9 h-9 rounded-full bg-space-panel/80 border border-space-border flex items-center justify-center text-gray-400 hover:text-neon-cyan hover:border-neon-cyan/40 opacity-0 hover:opacity-100 focus-visible:opacity-100 transition-opacity"
      title={t('label.cleanExit')}
    >
      ✕
    </button>
  )}
  </div>
)
}
