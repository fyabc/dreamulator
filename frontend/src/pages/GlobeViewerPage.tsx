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
import { useQuery } from '@tanstack/react-query'
import * as THREE from 'three'
import GlobeViewer, { type GlobeVertex, type GlobeRegion, type GlobeRegionFlight } from '../viewers/GlobeViewer'
import MapStatusBar from '../components/map/MapStatusBar'
import MapLayerPanel from '../components/map/MapLayerPanel'
import { activeMainLayerId } from '../components/map/layerStateInit'
import MapCellInspector, { MobileCellCard } from '../components/map/MapCellInspector'
import SunControl from '../components/map/SunControl'
import { MapTimeControl } from '../components/map/TimeControl'
import AwaitingBuildBanner from '../components/map/AwaitingBuildBanner'
import ClimateLegend from '../components/map/ClimateLegend'
import RegionWindowPanel from '../components/map/RegionWindowPanel'
import { MapBodySelector, MapLayerDrawer, MapWorkbenchToolbar } from '../components/map/MapWorkbenchToolbar'
import { trialButtonId, trialPanelId } from '../components/map/MapTemperatureTrial'
import useGPUTerrain from '../viewers/map/useGPUTerrain'
import { GRID_H, GRID_W } from '../playground/temperatureDraft'
import { useMapTemperatureTrial } from '../viewers/map/useTemperatureTrialPreview'
import { useMapDisplayLayers } from '../viewers/map/useMapDisplayLayers'
import useRafCoalesced from '../viewers/map/useRafCoalesced'
import { buildCellKDTree, type KDTree3D } from '../components/map/utils/kdtree'
import type { PointProjector, VoronoiCell } from '../viewers/map/types'
import { normalisedToMeters } from '../viewers/map/utils/mapCoords'
import GlobeCurrentArrows from '../components/map/GlobeCurrentArrows'
import GlobeWindArrows from '../components/map/GlobeWindArrows'
import FlowParticles from '../components/map/FlowParticles'
import ImportElevationButton from '../components/map/ImportElevationButton'
import TerrainSourceSelect from '../components/map/TerrainSourceSelect'
import GeographyRasterButton from '../components/map/GeographyRasterButton'
import { usePlanetViewState } from '../viewers/map/usePlanetViewState'
import { readRegionBoundary, readRegionWindow, REGION_WINDOW_PARAM } from '../viewers/map/regionWindow'
import { savedGlobeRegion } from '../viewers/map/utils/globeRegionDetail'
import { isStaticMode } from '../api/mode'
import { openProjectRaster } from '../projects/elevationProject'
import { getProject, projectKey, worldDataPath } from '../projects/projectStore'

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

  const trial = useMapTemperatureTrial()
  const trialActive = trial.mode === 'trial' && !trial.ebm
  const vs = usePlanetViewState(worldName, planetId, 'globe', trialActive, trial.ebm)
  const {
    selectedBranch,
    cleanMode, setCleanMode,
    layerState, setLayerState, activeMainLayer,
    monthlyMode, handleMonthlyModeChange, selectMonth, displayingMonthly, layerDetail,
    particleMode, setParticleMode,
    sunLongitudeDeg, setSunLongitudeDeg, seasonDeg, setSeasonDeg,
    dayNightEnabled, setDayNightEnabled, solarDeclination, axialTiltDeg,
    selectedPlanet, mapPlanets, meta, metaError, elevError, cvtMeshError, awaitingBuild,
    bodyByName, planetRadiusM,
    elevation, elevationDims, cvtMesh, voronoiCells, cellIdMap, terrainSource, setTerrainSource, canSelectTerrainSource, meshTextureSize,
    scalarThematic, koppenTexture, monthlyData, monthlyLoading, monthlyMonth, yearlyData, uccTexture,
    cursor, setCursor, handleCellHover, selectedCells,
    selectCell, clearSelection,
    hoveredCell, hoveredCellData, inspectorCell, selectedCellData, selectedCellObjects,
    importMsg, setImportMsg, handleImported,
  } = vs
  const display = useMapDisplayLayers(trial, layerState, setLayerState, cvtMesh, monthlyData, Boolean(uccTexture))

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
  const rawWindow = searchParams.get(REGION_WINDOW_PARAM)
  const regionBoundary = useMemo(() => readRegionBoundary(rawWindow, planetRadiusM / 1000),
    [rawWindow, planetRadiusM])
  const regionFocus = useMemo(() => readRegionWindow(rawWindow, planetRadiusM / 1000), [rawWindow, planetRadiusM])
  const [regionMoveRevision, setRegionMoveRevision] = useState(0)
  const scalePreview = searchParams.get('zoomPreview') === '1' && !cleanMode
  const [regionFlight, setRegionFlight] = useState<GlobeRegionFlight | null>(null)
  const detailEnabled = isStaticMode() && scalePreview && activeMainLayer === 'terrain' && !!worldName && !!selectedPlanet && !!regionFocus
  const savedWorld = useQuery({ queryKey: projectKey(worldName ?? ''), queryFn: () => getProject(worldName!), enabled: detailEnabled, retry: false })
  const savedDetail = detailEnabled ? savedGlobeRegion(savedWorld.data, {
    world: worldName!, planet: selectedPlanet!, branch: selectedBranch, radiusKm: planetRadiusM / 1000, selection: regionFocus!,
  }) : null
  const detail = useQuery({ queryKey: [...projectKey(worldName ?? ''), 'globe-detail', savedDetail?.result.id],
    queryFn: async () => ({ raster: await openProjectRaster(savedDetail!.result), frame: savedDetail!.frame }),
    enabled: savedDetail !== null, gcTime: 0, retry: false })
  const regionDetail = savedDetail ? detail.data : null

  const globeProjectRef = useRef<((lon: number, lat: number) => { x: number; y: number; edgeFade: number; zoomScale: number; ex: number; ey: number; nx: number; ny: number } | null) | null>(null)
  const globePointProjectRef = useRef<PointProjector | null>(null)
  const [globeZoom, setGlobeZoom] = useState(1)

  const elevMin = meta?.elevation_min_m ?? -11000
  const elevMax = meta?.elevation_max_m ?? 9000
  const seaLevel = meta?.sea_level_m ?? 0

  // --- GPU texture ---
  // Opacity sliders fire many events per frame; coalesce so the composite
  // pass (and any data-driven re-bake) runs at most once per animation frame.
  const renderLayers = useRafCoalesced(display.state.layers)
  const trialTerrain = trial.preview?.terrain

  const { texture: terrainTexture, renderComposite } = useGPUTerrain({
    elevation,
    width: elevationDims.w, height: elevationDims.h,
    terrainSource, meshWidth: meshTextureSize.width, meshHeight: meshTextureSize.height,
    seaLevel, elevMinM: elevMin, elevMaxM: elevMax,
    layers: renderLayers,
    cvtMesh,
    cellIdMap,
    scalarThematic,
    koppenTexture,
    uccTexture,
    flipHorizontal: false,
    ...(trialTerrain && {
      elevation: trialTerrain.elevation, width: GRID_W, height: GRID_H,
      terrainSource: 'raster', meshWidth: GRID_W, meshHeight: GRID_H,
      seaLevel: trialTerrain.params.seaLevelM, elevMinM: trialTerrain.params.elevMinM, elevMaxM: trialTerrain.params.elevMaxM,
      cvtMesh: null, cellIdMap: null, monthlyTemperature: display.texture,
    }),
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
    const mapW = elevationDims.w
    const mapH = elevationDims.h
    const px = Math.floor((((lon + 180) % 360 + 360) % 360) / 360 * mapW)
    const py = Math.min(mapH - 1, Math.floor(((90 - lat) / 180) * mapH))
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

      const meshElev = terrainSource === 'mesh' && cellId >= 0 ? voronoiCells[cellId]?.elevation : undefined
      setCursor({
        lon: Math.round(lon * 100) / 100,
        lat: Math.round(lat * 100) / 100,
        elevation: meshElev == null ? elev : (meshElev - elevMin) / (elevMax - elevMin || 1),
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
  }, [elevation, elevationDims, elevMin, elevMax, kdTree, voronoiCells, terrainSource, handleCellHover, setCursor])

  const handleCellClickLonLat = useCallback((lon: number, lat: number, ctrlKey: boolean) => {
    if (!kdTree) {
      if (trialActive) handleCellHoverLonLat(lon, lat)
      return
    }
    const rad = THREE.MathUtils.degToRad(lat)
    const cosLat = Math.cos(rad)
    const cellId = kdTree.nearest(
      cosLat * Math.cos(THREE.MathUtils.degToRad(lon)),
      Math.sin(rad),
      cosLat * Math.sin(THREE.MathUtils.degToRad(lon)),
    )
    if (cellId < 0) return
    selectCell(cellId, ctrlKey)
  }, [kdTree, selectCell, trialActive, handleCellHoverLonLat])

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
  const trialReady = Boolean(worldName && selectedPlanet && meta && elevation)
  const openTrial = () => {
    setLeftPanelOpen(false)
    trial.openPanel()
  }

  // --- Render ---
  if (!worldName) {
    return <div className="flex items-center justify-center h-full text-gray-500">{t('status.noWorldOrPlanet')}</div>
  }

  const currentPlanet = selectedPlanet ? bodyByName.get(selectedPlanet) : undefined
  const inspection = <div className="space-y-3">
    <div className="border-b border-space-border pb-3">
      <MapTimeControl mesh={cvtMesh} trialMode={trialActive} preview={trial.preview}
        layer={trialActive ? display.trialInspectionLayer : vs.activeColorMode}
        monthlyData={monthlyData} loading={monthlyLoading} monthlyMode={monthlyMode}
        onMonthlyModeChange={handleMonthlyModeChange} monthIndex={monthlyMonth} onSelectMonth={selectMonth} />
    </div>
    <MapCellInspector trialMode={trialActive} trial={trial.preview} cursor={cursor}
    cell={inspectorCell} cvtMesh={cvtMesh} planetName={currentPlanet?.name ?? selectedPlanet} selectedCells={selectedCellObjects}
    activeColorMode={trialActive ? display.texture ? 'temperature' : 'terrain' : vs.activeColorMode} monthlyMode={monthlyMode} monthIndex={monthlyMonth}
    monthlyData={monthlyData} yearlyData={yearlyData} isEarth={worldName === 'earth'} seaLevelM={meta?.sea_level_m} />
  </div>
  const layers = <MapLayerPanel state={display.state} onChange={display.onChange} available={display.available} isEarth={worldName === 'earth'}
    monthlyMode={trialActive ? typeof trial.preview?.period === 'number' : monthlyMode} monthlyData={trialActive ? null : monthlyData}
    temperaturePeriodLabel={typeof trial.preview?.period === 'number' ? trial.preview.label : undefined}
    monthIndex={monthlyMonth} onMonthlyModeChange={handleMonthlyModeChange}
    detail={layerDetail(display.available, display.state.layers.temperature > 0 && Boolean(trial.preview))}
    particleMode={particleMode} onParticleModeChange={setParticleMode} />
  const legend = !cleanMode && displayTexture && <ClimateLegend layer={activeMainLayerId(display.state)} mesh={cvtMesh}
    displayingMonthly={displayingMonthly} monthlyMode={monthlyMode} monthlyData={monthlyData} monthlyLoading={monthlyLoading}
    monthIndex={monthlyMonth} yearlyData={yearlyData} meta={meta}
    preview={trialActive ? trial.preview : null} />

  return (
    <div className={cleanMode
      ? 'fixed inset-0 z-40 flex flex-col bg-[#030308]'
      : 'atlas-workbench flex flex-col'}>
      {!cleanMode && (
      <MapWorkbenchToolbar title={currentPlanet?.name ?? selectedPlanet ?? t('title.globe')} view="globe"
        backTo={searchParams.has('draft') || (!meta?.browser_heightmap && searchParams.has('climateResult')) ? worldDataPath(worldName, selectedBranch) :
          `/worlds/${worldName}${selectedBranch ? `?branch=${encodeURIComponent(selectedBranch)}` : ''}`}
        switchTo={selectedPlanet ? `/worlds/${worldName}/map/${selectedPlanet}${mapQS}` : undefined}
        regionControls={selectedPlanet && (elevation || cvtMesh) ? (
          <RegionWindowPanel key={selectedPlanet} world={worldName} planet={selectedPlanet}
            climateResult={meta?.browser_heightmap && trial.mode === 'trial' ? searchParams.get('climateResult') ?? undefined : undefined}
            branch={selectedBranch} radiusKm={planetRadiusM / 1000}
            modeControl={trialReady ? { mode: trial.mode, onChange: trial.selectMode } : undefined}
            onMoveToRegion={() => {
              setRegionFlight(null)
              setRegionMoveRevision((revision) => revision + 1)
            }}
            onRegionScale={scalePreview && regionFocus
              ? (scale) => setRegionFlight({ window: regionFocus, scale, radiusKm: planetRadiusM / 1000 }) : undefined}
            scaleDetail={!trialActive && detailEnabled ? regionDetail ? 'ready' : savedWorld.isPending || (savedDetail && detail.isPending)
              ? 'loading' : savedWorld.isError || detail.isError ? 'failed' : 'missing' : undefined}
            scaleAltitudeKm={globeZoom > 1 ? (globeZoom - 1) * planetRadiusM / 1000 : undefined}
            selectedPoint={selectedCells.size === 1 ? selectedCellData : null} />
        ) : undefined}
        trialPanel={trialReady ? { id: trialPanelId, buttonId: trialButtonId, open: trial.open, onToggle: trial.open ? trial.closePanel : openTrial } : undefined}
        layersOpen={leftPanelOpen && !trial.open} onToggleLayers={() => {
          if (trial.open) trial.closePanel()
          setLeftPanelOpen(open => !open)
        }}>
        {!trialActive && canSelectTerrainSource && <TerrainSourceSelect value={terrainSource} onChange={setTerrainSource}
          width={elevationDims.w} height={elevationDims.h} cells={cvtMesh?.cells.length} />}
        {selectedPlanet && (
          <ImportElevationButton
            worldName={worldName!}
            planetId={selectedPlanet}
            branch={selectedBranch}
            onImported={(result) => {
              trial.replaceElevation()
              handleImported(result)
            }}
          />
        )}
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

        {!!mapPlanets?.length && <MapBodySelector planets={mapPlanets} selected={selectedPlanet}
          nameOf={id => bodyByName.get(id)?.name ?? id} onSelect={id => {
            const next = new URLSearchParams(searchParams)
            next.delete(REGION_WINDOW_PARAM)
            next.delete('draft')
            next.delete('climateResult')
            const qs = next.toString()
            navigate(`/worlds/${worldName}/globe/${id}${qs ? `?${qs}` : ''}`)
          }} />}
        {!meta?.browser_heightmap && <Link to={`/worlds/${worldName}/viewer3d${stellarQS}`} className="atlas-tool-button text-sm">
          {t('label.stellarShort')}
        </Link>}
      </MapWorkbenchToolbar>
      )}

      {/* Error / info banner */}
      {!cleanMode && importMsg && (
        <div className={`border-b px-4 py-2 text-sm text-center ${
          importMsg.ok ? 'bg-green-900/20 border-green-700/30 text-green-300' : 'bg-red-900/20 border-red-700/30 text-red-300'
        }`}>
          {importMsg.text}
          {importMsg.temperatureOrigin && trialReady && <button type="button" onClick={openTrial}
            className="mx-2 inline-flex min-h-11 items-center font-medium text-neon-cyan underline underline-offset-4">
            {t('msg.tryTemperature')}
          </button>}
        </div>
      )}
      {awaitingBuild && !cleanMode && (
        <AwaitingBuildBanner world={worldName} branch={selectedBranch} />
      )}
      {(metaError || elevError || cvtMeshError) && (
        <div className="bg-red-900/20 border-b border-red-700/30 px-4 py-2 text-sm text-red-300 text-center">
          {t('label.dataLoadFailed')}
        </div>
      )}

      {/* Main content */}
      <div className="relative isolate min-h-0 flex-1">
        {/* === Mobile layout (visible only < md) === */}
        <div className="flex flex-col min-h-0 lg:hidden absolute inset-0">
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
                onTransition={meta?.browser_heightmap ? undefined : handleTransition}
                onCellHover={handleCellHoverLonLat}
                onCellClick={handleCellClickLonLat}
                onHoverOut={() => { handleCellHover(null); setCursor(null) }}
                onDistanceChange={setGlobeZoom}
                vertices={globeVertices}
                regions={globeRegions}
                hoveredCellId={cleanMode ? null : hoveredCell}
                selectedCellIds={cleanMode ? emptySelection : selectedCells}
                regionBoundary={cleanMode ? null : regionBoundary}
                regionFocus={regionFocus}
                regionMoveRevision={regionMoveRevision}
                scalePreview={scalePreview}
                regionFlight={scalePreview && regionFlight?.window === regionFocus ? regionFlight : null}
                regionDetail={regionDetail}
                sunLongitudeDeg={sunLongitudeDeg}
                solarDeclinationDeg={solarDeclination}
                dayNight={dayNightEnabled}
                autoSpin={autoSpin}
                chrome={!cleanMode}
                interactive={!cleanMode}
                frameless={cleanMode}
                globeProjectRef={globeProjectRef}
                globePointProjectRef={globePointProjectRef}
              />
            )}
            {!trialActive && <>{particleMode ? (
              <>
                <FlowParticles
                  projectRef={globePointProjectRef}
                  kind="current"
                  cells={voronoiCells}
                  opacity={layerState.layers.currents ?? 0}
                  planetRadiusM={planetRadiusM}
                  cellIdMap={cellIdMap}
                  meshWidth={meshTextureSize.width}
                  meshHeight={meshTextureSize.height}
                />
                <FlowParticles
                  projectRef={globePointProjectRef}
                  kind="wind"
                  cells={voronoiCells}
                  opacity={layerState.layers.winds ?? 0}
                  monthlyWindEast={monthlyMode ? monthlyData?.windEastMonthly ?? null : null}
                  monthlyWindNorth={monthlyMode ? monthlyData?.windNorthMonthly ?? null : null}
                  month={monthlyMonth}
                  planetRadiusM={planetRadiusM}
                />
              </>
            ) : (
              <>
                <GlobeCurrentArrows
                  projectRef={globeProjectRef}
                  voronoiCells={voronoiCells}
                  currentOpacity={layerState.layers.currents ?? 0}
                />
                <GlobeWindArrows
                  projectRef={globeProjectRef}
                  voronoiCells={voronoiCells}
                  windOpacity={layerState.layers.winds ?? 0}
                  monthlyWindEast={monthlyMode ? monthlyData?.windEastMonthly ?? null : null}
                  monthlyWindNorth={monthlyMode ? monthlyData?.windNorthMonthly ?? null : null}
                  month={monthlyMonth}
                />
              </>
            )}
            <GlobeCurrentArrows
              projectRef={globeProjectRef}
              voronoiCells={voronoiCells}
              currentOpacity={layerState.layers.currentError ?? 0}
              deviation
            />
            <GlobeWindArrows
              projectRef={globeProjectRef}
              voronoiCells={voronoiCells}
              windOpacity={layerState.layers.windError ?? 0}
              deviation
            />
            </>}
            {legend}
          </div>
          {!cleanMode && (
            <MobileCellCard
              seaLevelM={meta?.sea_level_m}
              cell={selectedCells.size === 1 ? selectedCellData : null}
              cursor={cursor}
              onClose={clearSelection}
              covered={trial.open}
              trialMode={trialActive} trial={trial.preview}
              inspection={inspection}
            />
          )}
        </div>

        {!cleanMode && !trial.open && leftPanelOpen && (
          <MapLayerDrawer onClose={() => setLeftPanelOpen(false)}>
            {layers}
            <div className="mt-3 pt-3 border-t border-space-border">
              <SunControl
                sunLongitudeDeg={sunLongitudeDeg}
                onLongitudeChange={setSunLongitudeDeg}
                seasonDeg={seasonDeg} onSeasonChange={setSeasonDeg} solarDeclination={solarDeclination} axialTiltDeg={axialTiltDeg}
                enabled={dayNightEnabled}
                onEnabledChange={setDayNightEnabled}
              />
            </div>
          </MapLayerDrawer>
        )}
      </div>

        {/* === Desktop layout (≥ md) === */}
        <div className="hidden lg:flex absolute inset-0">
          {/* Left panel: layers */}
          {!cleanMode && (
          <div className="w-56 shrink-0 bg-space-panel border-r border-space-border overflow-y-auto p-3 space-y-4">
            {layers}
            <div className="mt-3 pt-3 border-t border-space-border">
              <SunControl
                  sunLongitudeDeg={sunLongitudeDeg}
                  onLongitudeChange={setSunLongitudeDeg}
                  seasonDeg={seasonDeg} onSeasonChange={setSeasonDeg} solarDeclination={solarDeclination} axialTiltDeg={axialTiltDeg}
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
              regionBoundary={cleanMode ? null : regionBoundary}
              regionFocus={regionFocus}
              regionMoveRevision={regionMoveRevision}
              scalePreview={scalePreview}
              regionFlight={scalePreview && regionFlight?.window === regionFocus ? regionFlight : null}
              regionDetail={regionDetail}
              sunLongitudeDeg={sunLongitudeDeg}
              solarDeclinationDeg={solarDeclination}
              dayNight={dayNightEnabled}
              autoSpin={autoSpin}
              chrome={!cleanMode}
              interactive={!cleanMode}
              frameless={cleanMode}
              globeProjectRef={globeProjectRef}
              globePointProjectRef={globePointProjectRef}
            />
          )}
          {!trialActive && <>{particleMode ? (
            <>
              <FlowParticles
                projectRef={globePointProjectRef}
                kind="current"
                cells={voronoiCells}
                opacity={layerState.layers.currents ?? 0}
                planetRadiusM={planetRadiusM}
                cellIdMap={cellIdMap}
                meshWidth={meshTextureSize.width}
                meshHeight={meshTextureSize.height}
              />
              <FlowParticles
                projectRef={globePointProjectRef}
                kind="wind"
                cells={voronoiCells}
                opacity={layerState.layers.winds ?? 0}
                monthlyWindEast={monthlyMode ? monthlyData?.windEastMonthly ?? null : null}
                monthlyWindNorth={monthlyMode ? monthlyData?.windNorthMonthly ?? null : null}
                month={monthlyMonth}
                planetRadiusM={planetRadiusM}
              />
            </>
          ) : (
            <>
              <GlobeCurrentArrows
                projectRef={globeProjectRef}
                voronoiCells={voronoiCells}
                currentOpacity={layerState.layers.currents ?? 0}
              />
              <GlobeWindArrows
                projectRef={globeProjectRef}
                voronoiCells={voronoiCells}
                windOpacity={layerState.layers.winds ?? 0}
                monthlyWindEast={monthlyMode ? monthlyData?.windEastMonthly ?? null : null}
                monthlyWindNorth={monthlyMode ? monthlyData?.windNorthMonthly ?? null : null}
                month={monthlyMonth}
              />
            </>
          )}
          <GlobeCurrentArrows
            projectRef={globeProjectRef}
            voronoiCells={voronoiCells}
            currentOpacity={layerState.layers.currentError ?? 0}
            deviation
          />
          <GlobeWindArrows
            projectRef={globeProjectRef}
            voronoiCells={voronoiCells}
            windOpacity={layerState.layers.windError ?? 0}
            deviation
          />
          </>}
          {legend}

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
          <MapStatusBar cursor={cursor} zoom={globeZoom} hoveredCell={trialActive ? null : hoveredCellData} trial={trial.preview} />
        )}
      </div>

      {/* Right panel: cell inspector */}
      {!cleanMode && (
      <div ref={element => { if (element) element.inert = trial.open }}
        className="w-52 shrink-0 bg-space-panel/50 border-l border-space-border overflow-y-auto p-3">
        {inspection}
      </div>
      )}
    </div>

    <div className="contents" ref={trial.attachPanel} />

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
