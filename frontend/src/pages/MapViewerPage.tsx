/**
 * MapViewerPage — full-page read-only map viewer with Three.js terrain + SVG overlay.
 *
 * Route: /worlds/:worldName/map and /worlds/:worldName/map/:planetId
 *
 * Shared posture (layers / branch / lighting / monthly climate / cell
 * selection) lives in usePlanetViewState — this page adds the 2D renderer
 * (Three.js plane + SVG overlay), the minimap, and the map-specific panels.
 */

import { useEffect, useMemo, useState } from 'react'
import useIsDesktop from '../hooks/useIsDesktop'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import ImportElevationButton from '../components/map/ImportElevationButton'
import TerrainSourceSelect from '../components/map/TerrainSourceSelect'
import GeographyRasterButton from '../components/map/GeographyRasterButton'
import MapViewer from '../components/map/MapViewer'
import AtlasIcon from '../components/AtlasIcon'
import MapLayerPanel from '../components/map/MapLayerPanel'
import { activeMainLayerId } from '../components/map/layerStateInit'
import MapCellInspector, { MobileCellCard } from '../components/map/MapCellInspector'
import { inspectorDesktopPane, MapInspectorPane } from '../components/map/MapInspectorFields'
import MapLegend from '../components/map/MapLegend'
import ClimateLegend from '../components/map/ClimateLegend'
import MapStatusBar from '../components/map/MapStatusBar'
import MapMinimap from '../components/map/MapMinimap'
import SunControl from '../components/map/SunControl'
import { MapTimeControl } from '../components/map/TimeControl'
import AwaitingBuildBanner from '../components/map/AwaitingBuildBanner'
import MapDataLoading from '../components/map/MapDataLoading'
import QuickLayerSwitch from '../components/map/QuickLayerSwitch'
import TimeModeToggle from '../components/map/TimeModeToggle'
import RegionWindowPanel from '../components/map/RegionWindowPanel'
import MapResultModeControl from '../components/map/MapResultModeControl'
import WorldContextSlot from '../components/map/WorldContextSlot'
import { MapBodySelector, MapLayerDrawer, MapWorkbenchToolbar } from '../components/map/MapWorkbenchToolbar'
import { trialButtonId, trialPanelId } from '../components/map/MapTemperatureTrial'
import { readRegionBoundary, readRegionWindow, REGION_WINDOW_PARAM } from '../viewers/map/regionWindow'
import { isMonthlyLayer } from '../components/map/climateTime'
import { usePlanetViewState } from '../viewers/map/usePlanetViewState'
import { useMapTemperatureTrial } from '../viewers/map/useTemperatureTrialPreview'
import { useMapDisplayLayers } from '../viewers/map/useMapDisplayLayers'

export default function MapViewerPage() {
  const { worldName, planetId: routePlanetId } = useParams<{
    worldName: string
    planetId?: string
  }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation('map')

  const trial = useMapTemperatureTrial()
  const trialActive = trial.mode === 'trial' && !trial.ebm
  const vs = usePlanetViewState(worldName, routePlanetId, 'map', trialActive, trial.ebm)
  const {
    selectedBranch,
    cleanMode, setCleanMode,
    layerState, setLayerState, activeMainLayer,
    monthlyMode, handleMonthlyModeChange, selectMonth, displayingMonthly, layerDetail,
    particleMode, setParticleMode,
    sunLongitudeDeg, setSunLongitudeDeg, seasonDeg, setSeasonDeg,
    dayNightEnabled, setDayNightEnabled, solarDeclination, axialTiltDeg,
    selectedPlanet, mapPlanets, meta, bodyByName, currentPlanetName, planetRadiusM,
    worldPlanetsError, platesError, metaError, elevError, cvtMeshError,
    elevation, elevationDims, cvtMesh, voronoiCells, awaitingBuild, terrainSource, setTerrainSource, canSelectTerrainSource,
    scalarThematic, koppenTexture, monthlyData, monthlyLoading, monthlyMonth, yearlyData, uccTexture,
    cursor, setCursor, hoveredCell, handleCellHover, selectedCells,
    selectCell, clearSelection,
    hoveredCellData, inspectorCell, selectedCellData, selectedCellObjects,
    importMsg, setImportMsg, handleImported,
  } = vs
  const display = useMapDisplayLayers(trial, layerState, setLayerState, cvtMesh, monthlyData, Boolean(uccTexture))
  const elevationReady = Boolean(elevation && elevationDims.w > 0)
  const desktopLayout = useIsDesktop()
  const [mapPainted, setMapPainted] = useState(false)
  useEffect(() => {
    if (!elevationReady) setMapPainted(false)
  }, [elevationReady, selectedPlanet, selectedBranch, terrainSource])
  const loadingMessage = elevError ? t('label.noMapData')
    : elevation && elevationDims.w === 0 ? t('label.decodingHeightmap') : t('label.mapDataLoading')
  const [leftPanelCollapsed, setLeftPanelCollapsed] = useState(() =>
    localStorage.getItem('dreamulator-map-left-panel') === '1')
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(() =>
    localStorage.getItem('dreamulator-map-right-panel') === '1')
  useEffect(() => {
    try { localStorage.setItem('dreamulator-map-left-panel', leftPanelCollapsed ? '1' : '0') } catch { return }
  }, [leftPanelCollapsed])
  useEffect(() => {
    try { localStorage.setItem('dreamulator-map-right-panel', rightPanelCollapsed ? '1' : '0') } catch { return }
  }, [rightPanelCollapsed])
  // Stable empty set — clean mode suppresses hover/selection highlights without
  // changing cell-picking state underneath.
  const emptySelection = useMemo(() => new Set<number>(), [])
  const rawWindow = searchParams.get(REGION_WINDOW_PARAM)
  const regionBoundary = useMemo(() => readRegionBoundary(rawWindow, planetRadiusM / 1000),
    [rawWindow, planetRadiusM])
  const regionFocus = useMemo(() => readRegionWindow(rawWindow, planetRadiusM / 1000), [rawWindow, planetRadiusM])
  const [regionMoveRevision, setRegionMoveRevision] = useState(0)
  const [minimapOpen, setMinimapOpen] = useState(true)
  const [viewResetRevision, setViewResetRevision] = useState(0)
  const [regionPicking, setRegionPicking] = useState(false)
  const [regionPickedPoint, setRegionPickedPoint] = useState<{ lon: number; lat: number } | null>(null)

  // Left panel drawer (mobile only)
  const [leftPanelOpen, setLeftPanelOpen] = useState(false)
  const trialFromClimate = searchParams.get('trial') === 'climate'
  const trialReady = Boolean(worldName && selectedPlanet && meta && elevation)
  const trialOpen = trial.open
  const openTrial = () => {
    setLeftPanelOpen(false)
    trial.openPanel()
  }

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

  // Forward current lighting (sun/season/night) + branch to the 3D globe link.
  const globeSearch = new URLSearchParams(searchParams)
  if (!meta?.browser_heightmap) globeSearch.delete('trial')
  const globeQS = globeSearch.size ? `?${globeSearch}` : ''
  const backSearch = new URLSearchParams()
  if (selectedBranch) backSearch.set('branch', selectedBranch)
  if (searchParams.has('draft') || (!meta?.browser_heightmap && searchParams.has('climateResult'))) {
    backSearch.set('tab', 'data')
  } else if (trialFromClimate) {
    backSearch.set('tab', 'climate')
    if (selectedPlanet) backSearch.set('planet', selectedPlanet)
  }
  const inspectionLayer = trialActive ? display.trialInspectionLayer : vs.activeColorMode
  const showTimeControl = trialActive
    ? Boolean(trial.preview?.periods?.length) && inspectionLayer === 'temperature'
    : isMonthlyLayer(inspectionLayer) && (Boolean(monthlyData) || monthlyLoading)
  const inspection = <div className="space-y-3">
    {showTimeControl && <div className="border-b border-space-border pb-3">
      <MapTimeControl mesh={cvtMesh} trialMode={trialActive} preview={trial.preview}
        layer={inspectionLayer}
        monthlyData={monthlyData} loading={monthlyLoading} monthlyMode={monthlyMode} cell={trialActive ? null : inspectorCell}
        onMonthlyModeChange={handleMonthlyModeChange} monthIndex={monthlyMonth} onSelectMonth={selectMonth} />
    </div>}
    <MapCellInspector trialMode={trialActive} trial={trial.preview} cursor={cursor}
    cell={inspectorCell} cvtMesh={cvtMesh} planetName={currentPlanetName} selectedCells={selectedCellObjects}
    activeColorMode={trialActive ? display.texture ? 'temperature' : 'terrain' : vs.activeColorMode} monthlyMode={monthlyMode} monthIndex={monthlyMonth}
    monthlyData={monthlyData} yearlyData={yearlyData} isEarth={worldName === 'earth'} seaLevelM={meta?.sea_level_m} />
  </div>
  const layers = <MapLayerPanel state={display.state} onChange={display.onChange} available={display.available} isEarth={worldName === 'earth'}
    monthlyMode={trialActive ? typeof trial.preview?.period === 'number' : monthlyMode} monthlyData={trialActive ? null : monthlyData}
    temperaturePeriodLabel={typeof trial.preview?.period === 'number' ? trial.preview.label : undefined}
    monthIndex={monthlyMonth} onMonthlyModeChange={handleMonthlyModeChange}
    detail={layerDetail(display.available, display.state.layers.temperature > 0 && Boolean(trial.preview))}
    particleMode={particleMode} onParticleModeChange={setParticleMode} />
  const legend = (inline = false) => !cleanMode && <ClimateLegend inline={inline} layer={activeMainLayerId(display.state)} mesh={cvtMesh}
    displayingMonthly={displayingMonthly} monthlyMode={monthlyMode} monthlyData={monthlyData} monthlyLoading={monthlyLoading}
    monthIndex={monthlyMonth} yearlyData={yearlyData} meta={meta}
    preview={trialActive ? trial.preview : null} />

  if (!worldName) {
    return <div className="text-center py-12 text-gray-400">{t('status.noWorld')}</div>
  }

  return (
    <div className={cleanMode
      ? 'fixed inset-0 z-40 flex flex-col bg-[#030308]'
      : 'atlas-workbench flex flex-col'}>
      <WorldContextSlot>
        {trialReady && <MapResultModeControl mode={trial.mode} onChange={trial.selectMode}
          ready={Boolean(trial.available || trial.ebm)} />}
      </WorldContextSlot>
      {!cleanMode && (
      <MapWorkbenchToolbar title={currentPlanetName ?? selectedPlanet ?? t('title.mapFallback')} view="map"
        backTo={`/worlds/${worldName}${backSearch.size ? `?${backSearch}` : ''}`}
        switchTo={selectedPlanet ? `/worlds/${worldName}/globe/${selectedPlanet}${globeQS}` : undefined}
        timeControls={!trialActive && <TimeModeToggle monthlyMode={monthlyMode}
          onChange={handleMonthlyModeChange} />}
        layerControls={<QuickLayerSwitch state={display.state} onChange={display.onChange}
          available={display.available} disabled={trialActive} />}
        regionControls={selectedPlanet && (elevation || cvtMesh) ? (
          <RegionWindowPanel key={selectedPlanet} world={worldName} planet={selectedPlanet}
            climateResult={meta?.browser_heightmap && trial.mode === 'trial' ? searchParams.get('climateResult') ?? undefined : undefined}
            branch={selectedBranch} radiusKm={planetRadiusM / 1000}
            onMoveToRegion={() => setRegionMoveRevision((revision) => revision + 1)}
            selectedPoint={selectedCells.size === 1 ? selectedCellData : null}
            pickedPoint={regionPickedPoint}
            onPickModeChange={setRegionPicking} />
        ) : undefined}
        trialPanel={trialReady ? { id: trialPanelId, buttonId: trialButtonId, open: trialOpen, onToggle: trialOpen ? trial.closePanel : openTrial } : undefined}
        layersOpen={leftPanelOpen && !trialOpen} onToggleLayers={() => {
          if (trialOpen) trial.closePanel()
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
            const qs = selectedBranch ? `?branch=${encodeURIComponent(selectedBranch)}` : ''
            navigate(`/worlds/${worldName}/map/${id}${qs}`)
          }} />}
      </MapWorkbenchToolbar>
      )}

      {awaitingBuild && !cleanMode && (
        <AwaitingBuildBanner world={worldName} branch={selectedBranch} />
      )}
      {/* Error banner */}
      {(metaError || elevError || cvtMeshError || worldPlanetsError) && (
        <div className="bg-red-900/20 border-b border-red-700/30 px-4 py-2 text-sm text-red-300 text-center">
          {t('label.dataLoadFailed')}
        </div>
      )}

      {/* Import result banner */}
      {!cleanMode && importMsg && (
        <div
          className={`${
            importMsg.ok
              ? 'bg-green-900/20 border-green-700/30 text-green-300'
              : 'bg-red-900/20 border-red-700/30 text-red-300'
          } border-b px-4 py-2 text-sm text-center`}
        >
          {importMsg.text}
          {importMsg.temperatureOrigin && trialReady && <button type="button" onClick={openTrial}
            className="mx-2 inline-flex min-h-11 items-center font-medium text-neon-cyan underline underline-offset-4">
            {t('msg.tryTemperature')}
          </button>}
        </div>
      )}

      {/* Main content */}
      <div className="relative isolate flex min-h-0 flex-1">
        {/* === Mobile layout (default, hidden ≥ md) === */}
        <div className="flex flex-col flex-1 min-w-0 lg:hidden">
          {/* Map area — full width */}
          <div className="flex-1 flex flex-col min-h-0">
            {elevationReady ? (
              <>
                <div className="relative flex-1 min-h-0">
                  {!desktopLayout && <MapViewer
                    metadata={meta ?? null}
                    elevation={elevation}
                    terrainSource={terrainSource}
                    voronoiCells={voronoiCells}
                    cvtMesh={cvtMesh}
                    layers={display.state.layers}
                    trialTemperature={display.texture}
                    trialTerrain={trial.preview?.terrain}

                    onCursorMove={setCursor}
                    onCellHover={handleCellHover}
                    onCellClick={selectCell}
                    onPickPoint={regionPicking ? setRegionPickedPoint : undefined}
                    onClearSelection={clearSelection}
                    onReady={() => setMapPainted(true)}
                    hoveredCell={cleanMode ? null : hoveredCell}
                    selectedCells={cleanMode ? emptySelection : selectedCells}
                    regionBoundary={cleanMode ? null : regionBoundary}
                    regionFocus={regionFocus}
                    regionMoveRevision={regionMoveRevision}
                    sunLongitudeDeg={sunLongitudeDeg}
                    solarDeclinationDeg={solarDeclination}
                    dayNight={dayNightEnabled}
                    scalarThematic={scalarThematic}
                    koppenTexture={koppenTexture}
                    uccTexture={uccTexture}
                    monthlyWindEast={monthlyMode ? monthlyData?.windEastMonthly ?? null : null}
                    monthlyWindNorth={monthlyMode ? monthlyData?.windNorthMonthly ?? null : null}
                    month={monthlyMonth}
                    particleMode={particleMode}
                    planetRadiusM={planetRadiusM}
                    showGraticule={!cleanMode}
                    onZoomChange={setDisplayZoom}
                    onViewStateChange={setViewState}
                    viewResetRevision={viewResetRevision}
                    lowMemory
                  />}
                  {legend()}
                  {!mapPainted && (
                    <div className="absolute inset-0 z-20 flex bg-[#0a0a1a]">
                      <MapDataLoading message={t('label.generatingTexture')} />
                    </div>
                  )}
                </div>
                {!cleanMode && (
                  <MobileCellCard
                    seaLevelM={meta?.sea_level_m}
                    cell={selectedCells.size === 1 ? selectedCellData : null}
                    cursor={cursor}
                    onClose={clearSelection}
                    covered={trialOpen}
                    trialMode={trialActive} trial={trial.preview}
                    inspection={inspection}
                  />
                )}
              </>
            ) : (
              <MapDataLoading message={loadingMessage} />
            )}
          </div>

          {!cleanMode && !trialOpen && leftPanelOpen && (
            <MapLayerDrawer onClose={() => setLeftPanelOpen(false)}>
              {layers}
              {platesError && selectedPlanet && (
                <div className="text-xs text-gray-500 pt-2">
                  {t('msg.noPlateData')}
                </div>
              )}
              <div className="pt-3 border-t border-space-border">
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

        {/* === Desktop layout (≥ lg, hidden by default) === */}
        <div className="hidden lg:flex flex-1 min-h-0">
          {/* Left panel: layers */}
          {!cleanMode && !leftPanelCollapsed && (
          <div className="w-48 shrink-0 bg-space-panel border-r border-space-border overflow-y-auto">
            <div className="flex items-center gap-1.5 border-b border-space-border px-2">
              <button type="button" onClick={() => setLeftPanelCollapsed(true)}
                title={t('workbench.collapseLayerPanel')} aria-label={t('workbench.collapseLayerPanel')}
                className="inline-flex size-6 items-center justify-center rounded text-gray-400 hover:bg-space-surface hover:text-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan">
                <AtlasIcon name="back" className="size-3.5" />
              </button>
              <h2 className="text-xs font-semibold uppercase leading-none tracking-wide text-gray-500">{t('workbench.layerPanel')}</h2>
            </div>
            <div className="space-y-4 p-3">
              {layers}
              {platesError && selectedPlanet && (
                <div className="text-xs text-gray-500 pt-2">
                  {t('msg.noPlateData')}
                </div>
              )}
              <div className="pt-3 border-t border-space-border">
                <SunControl
                  sunLongitudeDeg={sunLongitudeDeg}
                  onLongitudeChange={setSunLongitudeDeg}
                  seasonDeg={seasonDeg} onSeasonChange={setSeasonDeg} solarDeclination={solarDeclination} axialTiltDeg={axialTiltDeg}
                  enabled={dayNightEnabled}
                  onEnabledChange={setDayNightEnabled}
                />
              </div>
            </div>
          </div>
          )}

          {/* Center: map viewer */}
          <div className="flex-1 flex flex-col min-w-0">
            {elevationReady ? (
              <>
                <div className="flex-1 min-h-0 relative">
                  {desktopLayout && <MapViewer
                    metadata={meta ?? null}
                    elevation={elevation}
                    terrainSource={terrainSource}
                    voronoiCells={voronoiCells}
                    cvtMesh={cvtMesh}
                    layers={display.state.layers}
                    trialTemperature={display.texture}
                    trialTerrain={trial.preview?.terrain}

                    onCursorMove={setCursor}
                    onCellHover={handleCellHover}
                    onCellClick={selectCell}
                    onPickPoint={regionPicking ? setRegionPickedPoint : undefined}
                    onClearSelection={clearSelection}
                    onReady={() => setMapPainted(true)}
                    hoveredCell={cleanMode ? null : hoveredCell}
                    selectedCells={cleanMode ? emptySelection : selectedCells}
                    regionBoundary={cleanMode ? null : regionBoundary}
                    regionFocus={regionFocus}
                    regionMoveRevision={regionMoveRevision}
                    sunLongitudeDeg={sunLongitudeDeg}
                    solarDeclinationDeg={solarDeclination}
                    dayNight={dayNightEnabled}
                    scalarThematic={scalarThematic}
                    uccTexture={uccTexture}
                    koppenTexture={koppenTexture}
                    monthlyWindEast={monthlyMode ? monthlyData?.windEastMonthly ?? null : null}
                    monthlyWindNorth={monthlyMode ? monthlyData?.windNorthMonthly ?? null : null}
                    month={monthlyMonth}
                    particleMode={particleMode}
                    planetRadiusM={planetRadiusM}
                    showGraticule={!cleanMode}
                    onZoomChange={setDisplayZoom}
                    onViewStateChange={setViewState}
                    viewResetRevision={viewResetRevision}
                  />}

                  {!cleanMode && leftPanelCollapsed && (
                    <div className="absolute left-2 top-2 z-30">
                      <button type="button" onClick={() => setLeftPanelCollapsed(false)}
                        title={t('workbench.showLayerPanel')} aria-label={t('workbench.showLayerPanel')}
                        className="inline-flex size-8 items-center justify-center rounded border border-space-border bg-space-panel/90 text-gray-300 shadow-lg hover:border-neon-cyan hover:text-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan">
                        <AtlasIcon name="layers" className="size-4" />
                      </button>
                    </div>
                  )}
                  {!cleanMode && rightPanelCollapsed && (
                    <div className="absolute right-2 top-2 z-30">
                      <button type="button" onClick={() => setRightPanelCollapsed(false)}
                        title={t('workbench.showInspectorPanel')} aria-label={t('workbench.showInspectorPanel')}
                        className="inline-flex size-8 items-center justify-center rounded border border-space-border bg-space-panel/90 text-gray-300 shadow-lg hover:border-neon-cyan hover:text-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan">
                        <AtlasIcon name="chart" className="size-4" />
                      </button>
                    </div>
                  )}

                  {/* Recording control — float in the map view's bottom-right
                      corner.  Fully hidden in clean mode (zero UI while
                      recording; exit via Esc). */}
                  {!cleanMode && (
                  <div className="absolute bottom-3 right-3 z-30">
                    <button
                      onClick={() => setCleanMode(true)}
                      className="h-9 rounded-full flex items-center gap-1.5 px-2.5 text-sm border bg-space-panel/80 text-gray-400 border-space-border hover:text-neon-cyan hover:border-neon-cyan/40 shadow-lg transition-colors"
                      title={t('label.cleanMode')}
                      aria-label={t('label.cleanMode')}
                    >
                      <AtlasIcon name="frame" className="size-4" />
                      <span className="hidden text-xs xl:inline">{t('label.focus')}</span>
                    </button>
                  </div>
                  )}

                  {/* Base-map water/land legend — bottom-left, only while the
                      terrain or landsea base map is the active main layer. */}
                  {!cleanMode && (
                    <MapLegend visible={activeMainLayer === 'landsea'} />
                  )}
                  {!mapPainted && (
                    <div className="absolute inset-0 z-20 flex bg-[#0a0a1a]">
                      <MapDataLoading message={t('label.generatingTexture')} />
                    </div>
                  )}
                </div>
                {!cleanMode && (
                  <MapStatusBar cursor={cursor} zoom={displayZoom} hoveredCell={trialActive ? null : hoveredCellData} trial={trial.preview}
                    legend={legend(true)} onResetView={() => setViewResetRevision(revision => revision + 1)} />
                )}
              </>
            ) : (
              <MapDataLoading message={loadingMessage} />
            )}
          </div>

          {/* Right panel: cell inspector + minimap */}
          {!cleanMode && !rightPanelCollapsed && (
          <MapInspectorPane panelRef={element => { if (element) element.inert = trialOpen }}
            title={t('workbench.inspectorPanel')} onCollapse={() => setRightPanelCollapsed(true)}
            collapseLabel={t('workbench.collapseInspectorPanel')}
            className={`flex ${inspectorDesktopPane}`} footer={elevation && (
              <div className="shrink-0 border-t border-space-border">
                <div className="flex items-center justify-between gap-2 px-2">
                  <h3 className="text-xs font-semibold uppercase leading-none tracking-wide text-gray-500">
                    {t('label.minimap')}
                  </h3>
                  <button type="button" aria-expanded={minimapOpen}
                    title={t(minimapOpen ? 'workbench.collapseMinimap' : 'workbench.showMinimap')}
                    aria-label={t(minimapOpen ? 'workbench.collapseMinimap' : 'workbench.showMinimap')}
                    onClick={() => setMinimapOpen(open => !open)}
                    className="inline-flex size-6 items-center justify-center rounded text-gray-400 hover:bg-space-surface hover:text-neon-cyan focus-visible:outline focus-visible:outline-neon-cyan">
                    <AtlasIcon name="arrow" className={`size-3.5 transition-transform ${minimapOpen ? 'rotate-90' : '-rotate-90'}`} />
                  </button>
                </div>
                {minimapOpen && <div className="p-3 pt-1">
                  <MapMinimap
                    elevation={elevation}
                    width={meta?.width ?? 2048}
                    height={meta?.height ?? 1024}
                    seaLevelFraction={meta && meta.elevation_max_m > meta.elevation_min_m
                      ? (meta.sea_level_m - meta.elevation_min_m) / (meta.elevation_max_m - meta.elevation_min_m)
                      : 0}
                    mapCenter={viewState.mapCenter}
                    zoom={viewState.zoom}
                    containerWidth={viewState.containerWidth}
                    containerHeight={viewState.containerHeight}
                  />
                </div>}
              </div>
            )}>
            {inspection}
            {selectedCells.size > 1 && (
              <p className="text-[10px] text-gray-600 mt-2 text-center">
                {t('msg.escClearSelection')}
              </p>
            )}
          </MapInspectorPane>
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
