/**
 * MapViewerPage — full-page read-only map viewer with Three.js terrain + SVG overlay.
 *
 * Route: /worlds/:worldName/map and /worlds/:worldName/map/:planetId
 *
 * Shared posture (layers / branch / lighting / monthly climate / cell
 * selection) lives in usePlanetViewState — this page adds the 2D renderer
 * (Three.js plane + SVG overlay), the minimap, and the map-specific panels.
 */

import { useMemo, useState } from 'react'
import { useParams, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import ImportElevationButton from '../components/map/ImportElevationButton'
import TerrainSourceSelect from '../components/map/TerrainSourceSelect'
import GeographyRasterButton from '../components/map/GeographyRasterButton'
import MapViewer from '../components/map/MapViewer'
import MapLayerPanel from '../components/map/MapLayerPanel'
import { activeMainLayerId } from '../components/map/layerStateInit'
import MapCellInspector, { MobileCellCard } from '../components/map/MapCellInspector'
import { inspectorDesktopPane, MapInspectorPane } from '../components/map/MapInspectorFields'
import MapLegend from '../components/map/MapLegend'
import ClimateLegend from '../components/map/ClimateLegend'
import MapStatusBar from '../components/map/MapStatusBar'
import MapMinimap from '../components/map/MapMinimap'
import SunControl from '../components/map/SunControl'
import { canDownscale } from '../viewers/map/climateDownscale'
import { MapTimeControl } from '../components/map/TimeControl'
import AwaitingBuildBanner from '../components/map/AwaitingBuildBanner'
import RegionWindowPanel from '../components/map/RegionWindowPanel'
import { MapBodySelector, MapLayerDrawer, MapWorkbenchToolbar } from '../components/map/MapWorkbenchToolbar'
import { trialButtonId, trialPanelId } from '../components/map/MapTemperatureTrial'
import { readRegionBoundary, readRegionWindow, REGION_WINDOW_PARAM } from '../viewers/map/regionWindow'
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
    monthlyMode, handleMonthlyModeChange, selectMonth, displayingMonthly, downscale, setDownscale,
    particleMode, setParticleMode,
    sunLongitudeDeg, setSunLongitudeDeg, seasonDeg, setSeasonDeg,
    dayNightEnabled, setDayNightEnabled, solarDeclination, axialTiltDeg,
    selectedPlanet, mapPlanets, meta, bodyByName, currentPlanetName, planetRadiusM,
    worldPlanetsError, platesError, metaError, elevError, cvtMeshError,
    elevation, cvtMesh, voronoiCells, awaitingBuild, terrainSource, setTerrainSource,
    scalarThematic, koppenDownscale, monthlyData, monthlyLoading, monthlyMonth, yearlyData, uccTexture,
    cursor, setCursor, hoveredCell, handleCellHover, selectedCells,
    selectCell, clearSelection,
    hoveredCellData, inspectorCell, selectedCellData, selectedCellObjects,
    importMsg, setImportMsg, handleImported,
  } = vs
  const display = useMapDisplayLayers(trial, layerState, setLayerState, cvtMesh, monthlyData, Boolean(uccTexture))

  // Stable empty set — clean mode suppresses hover/selection highlights without
  // changing cell-picking state underneath.
  const emptySelection = useMemo(() => new Set<number>(), [])
  const rawWindow = searchParams.get(REGION_WINDOW_PARAM)
  const regionBoundary = useMemo(() => readRegionBoundary(rawWindow, planetRadiusM / 1000),
    [rawWindow, planetRadiusM])
  const regionFocus = useMemo(() => readRegionWindow(rawWindow, planetRadiusM / 1000), [rawWindow, planetRadiusM])
  const [regionMoveRevision, setRegionMoveRevision] = useState(0)

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
  globeSearch.delete('trial')
  const globeQS = globeSearch.size ? `?${globeSearch}` : ''
  const backSearch = new URLSearchParams()
  if (selectedBranch) backSearch.set('branch', selectedBranch)
  if (searchParams.has('draft') || searchParams.has('climateResult')) {
    backSearch.set('tab', 'data')
  } else if (trialFromClimate) {
    backSearch.set('tab', 'climate')
    if (selectedPlanet) backSearch.set('planet', selectedPlanet)
  }
  const inspection = <div className="space-y-3">
    <div className="border-b border-space-border pb-3">
      <MapTimeControl mesh={cvtMesh} trialMode={trialActive} preview={trial.preview}
        layer={trialActive ? display.trialInspectionLayer : vs.activeColorMode}
        monthlyData={monthlyData} loading={monthlyLoading} monthlyMode={monthlyMode}
        onMonthlyModeChange={handleMonthlyModeChange} monthIndex={monthlyMonth} onSelectMonth={selectMonth} />
    </div>
    <MapCellInspector trialMode={trialActive} trial={trial.preview} cursor={cursor}
    cell={inspectorCell} cvtMesh={cvtMesh} planetName={currentPlanetName} selectedCells={selectedCellObjects}
    activeColorMode={trialActive ? display.texture ? 'temperature' : 'terrain' : vs.activeColorMode} monthlyMode={monthlyMode} monthIndex={monthlyMonth}
    monthlyData={monthlyData} yearlyData={yearlyData} isEarth={worldName === 'earth'} seaLevelM={meta?.sea_level_m} />
  </div>
  const layers = <MapLayerPanel state={display.state} onChange={display.onChange} available={display.available} isEarth={worldName === 'earth'}
    monthlyMode={trialActive ? typeof trial.preview?.period === 'number' : monthlyMode} monthlyData={trialActive ? null : monthlyData}
    temperaturePeriodLabel={typeof trial.preview?.period === 'number' ? trial.preview.label : undefined}
    monthIndex={monthlyMonth} onMonthlyModeChange={handleMonthlyModeChange}
    detail={{ downscaled: downscale,
      onChange: setDownscale, pending: koppenDownscale.pending, available: trialActive
      ? display.state.layers.temperature > 0 && Boolean(trial.preview)
      : koppenDownscale.available || (Boolean(cvtMesh) && canDownscale(activeMainLayer) && display.available.has(activeMainLayer)) }}
    particleMode={particleMode} onParticleModeChange={setParticleMode} />
  const legend = !cleanMode && <ClimateLegend layer={activeMainLayerId(display.state)} mesh={cvtMesh}
    displayingMonthly={displayingMonthly} monthlyMode={monthlyMode} monthlyData={monthlyData} monthlyLoading={monthlyLoading}
    monthIndex={monthlyMonth} yearlyData={yearlyData} meta={meta} grayTerrain={terrainSource === 'gray'}
    preview={trialActive ? trial.preview : null} />

  if (!worldName) {
    return <div className="text-center py-12 text-gray-400">{t('status.noWorld')}</div>
  }

  return (
    <div className={cleanMode
      ? 'fixed inset-0 z-40 flex flex-col bg-[#030308]'
      : 'atlas-workbench flex flex-col'}>
      {!cleanMode && (
      <MapWorkbenchToolbar title={currentPlanetName ?? selectedPlanet ?? t('title.mapFallback')} view="map"
        backTo={`/worlds/${worldName}${backSearch.size ? `?${backSearch}` : ''}`}
        switchTo={selectedPlanet ? `/worlds/${worldName}/globe/${selectedPlanet}${globeQS}` : undefined}
        regionControls={selectedPlanet && (elevation || cvtMesh) ? (
          <RegionWindowPanel key={selectedPlanet} world={worldName} planet={selectedPlanet}
            branch={selectedBranch} radiusKm={planetRadiusM / 1000}
            modeControl={trialReady ? { mode: trial.mode, onChange: trial.selectMode } : undefined}
            onMoveToRegion={() => setRegionMoveRevision((revision) => revision + 1)}
            selectedPoint={selectedCells.size === 1 ? selectedCellData : null} />
        ) : undefined}
        trialPanel={trialReady ? { id: trialPanelId, buttonId: trialButtonId, open: trialOpen, onToggle: trialOpen ? trial.closePanel : openTrial } : undefined}
        layersOpen={leftPanelOpen && !trialOpen} onToggleLayers={() => {
          if (trialOpen) trial.closePanel()
          setLeftPanelOpen(open => !open)
        }}>
        {meta?.elevation_import && <TerrainSourceSelect value={terrainSource} onChange={setTerrainSource}
          width={meta.width} height={meta.height} cells={cvtMesh?.cells.length} />}
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
            {elevation ? (
              <>
                <div className="relative flex-1 min-h-0">
                  <MapViewer
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
                    hoveredCell={cleanMode ? null : hoveredCell}
                    selectedCells={cleanMode ? emptySelection : selectedCells}
                    regionBoundary={cleanMode ? null : regionBoundary}
                    regionFocus={regionFocus}
                    regionMoveRevision={regionMoveRevision}
                    sunLongitudeDeg={sunLongitudeDeg}
                    solarDeclinationDeg={solarDeclination}
                    dayNight={dayNightEnabled}
                    scalarThematic={scalarThematic}
                    koppenTexture={koppenDownscale.texture}
                    uccTexture={uccTexture}
                    monthlyWindEast={monthlyMode ? monthlyData?.windEastMonthly ?? null : null}
                    monthlyWindNorth={monthlyMode ? monthlyData?.windNorthMonthly ?? null : null}
                    month={monthlyMonth}
                    particleMode={particleMode}
                    planetRadiusM={planetRadiusM}
                    showGraticule={!cleanMode}
                    onZoomChange={setDisplayZoom}
                    onViewStateChange={setViewState}
                  />
                  {legend}
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
          {!cleanMode && (
          <div className="w-56 shrink-0 bg-space-panel border-r border-space-border overflow-y-auto p-3 space-y-4">
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
          )}

          {/* Center: map viewer */}
          <div className="flex-1 flex flex-col min-w-0">
            {elevation ? (
              <>
                <div className="flex-1 min-h-0 relative">
                  <MapViewer
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
                    koppenTexture={koppenDownscale.texture}
                    monthlyWindEast={monthlyMode ? monthlyData?.windEastMonthly ?? null : null}
                    monthlyWindNorth={monthlyMode ? monthlyData?.windNorthMonthly ?? null : null}
                    month={monthlyMonth}
                    particleMode={particleMode}
                    planetRadiusM={planetRadiusM}
                    showGraticule={!cleanMode}
                    onZoomChange={setDisplayZoom}
                    onViewStateChange={setViewState}
                  />
                  {legend}

                  {/* Recording control — float in the map view's bottom-right
                      corner.  Fully hidden in clean mode (zero UI while
                      recording; exit via Esc). */}
                  {!cleanMode && (
                  <div className="absolute bottom-3 right-3 z-30">
                    <button
                      onClick={() => setCleanMode(true)}
                      className="w-9 h-9 rounded-full flex items-center justify-center text-sm border bg-space-panel/80 text-gray-400 border-space-border hover:text-neon-cyan hover:border-neon-cyan/40 shadow-lg transition-colors"
                      title={t('label.cleanMode')}
                    >
                      ⛶
                    </button>
                  </div>
                  )}

                  {/* Base-map water/land legend — bottom-left, only while the
                      terrain or landsea base map is the active main layer. */}
                  {!cleanMode && (
                    <MapLegend visible={trialActive ? !display.texture : activeMainLayer === 'terrain' || activeMainLayer === 'landsea'} />
                  )}
                </div>
                {!cleanMode && (
                  <MapStatusBar cursor={cursor} zoom={displayZoom} hoveredCell={trialActive ? null : hoveredCellData} trial={trial.preview} />
                )}
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
          {!cleanMode && (
          <MapInspectorPane panelRef={element => { if (element) element.inert = trialOpen }}
            className={`flex ${inspectorDesktopPane}`} footer={elevation && (
              <div className="shrink-0 border-t border-space-border p-3">
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  {t('label.minimap')}
                </h3>
                <MapMinimap
                  elevation={elevation}
                  width={meta?.width ?? 2048}
                  height={meta?.height ?? 1024}
                  seaLevel={meta?.sea_level_m ?? 0.0}
                  mapCenter={viewState.mapCenter}
                  zoom={viewState.zoom}
                  containerWidth={viewState.containerWidth}
                  containerHeight={viewState.containerHeight}
                />
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
