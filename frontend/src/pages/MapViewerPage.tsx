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
import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import ImportElevationButton from '../components/map/ImportElevationButton'
import GeographyRasterButton from '../components/map/GeographyRasterButton'
import BranchSelector from '../components/BranchSelector'
import MapViewer from '../components/map/MapViewer'
import MapLayerPanel from '../components/map/MapLayerPanel'
import MapCellInspector, { MobileCellCard } from '../components/map/MapCellInspector'
import MapLegend from '../components/map/MapLegend'
import MapStatusBar from '../components/map/MapStatusBar'
import MapMinimap from '../components/map/MapMinimap'
import SunControl from '../components/map/SunControl'
import TimeControl from '../components/map/TimeControl'
import { usePlanetViewState } from '../viewers/map/usePlanetViewState'

export default function MapViewerPage() {
  const { worldName, planetId: routePlanetId } = useParams<{
    worldName: string
    planetId?: string
  }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { t } = useTranslation('map')

  const vs = usePlanetViewState(worldName, routePlanetId, 'map')
  const {
    selectedBranch, setSelectedBranch,
    cleanMode, setCleanMode,
    timelapsePlaying, setTimelapsePlaying, monthMs, setMonthMs,
    sunSweep, setSunSweep,
    layerState, setLayerState, activeMainLayer,
    monthlyMode, handleMonthlyModeChange, monthlyField,
    sunLongitudeDeg, setSunLongitudeDeg, seasonDeg, setSeasonDeg,
    dayNightEnabled, setDayNightEnabled, solarDeclination, axialTiltDeg,
    selectedPlanet, mapPlanets, meta, bodyByName, currentPlanetName,
    worldPlanetsError, platesError,
    elevation, cvtMesh, voronoiCells,
    monthlyThematic, monthlyData, monthlyMonth, yearlyData, uccTexture,
    cursor, setCursor, hoveredCell, handleCellHover, selectedCells,
    selectCell, clearSelection,
    hoveredCellData, inspectorCell, selectedCellData, selectedCellObjects,
    importMsg, setImportMsg, handleImported,
  } = vs

  // Stable empty set — clean mode suppresses hover/selection highlights without
  // changing cell-picking state underneath.
  const emptySelection = useMemo(() => new Set<number>(), [])

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

  // Forward current lighting (sun/season/night) + branch to the 3D globe link.
  const globeQS = searchParams.toString() ? `?${searchParams.toString()}` : ''

  if (!worldName) {
    return <div className="text-center py-12 text-gray-400">{t('status.noWorld')}</div>
  }

  return (
    <div className={cleanMode
      ? 'fixed inset-0 z-40 flex flex-col bg-[#030308]'
      : 'flex flex-col h-[calc(100vh-56px)] md:h-screen'}>
      {/* Top bar */}
      {!cleanMode && (
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
              const qs = selectedBranch ? `?branch=${encodeURIComponent(selectedBranch)}` : ''
              navigate(`/worlds/${worldName}/map/${e.target.value}${qs}`)
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
      )}

      {/* Error banner */}
      {worldPlanetsError && (
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
        </div>
      )}

      {/* Main content */}
      <div className="flex flex-1 min-h-0 relative">
        {/* === Mobile layout (default, hidden ≥ md) === */}
        <div className="flex flex-col flex-1 min-w-0 md:hidden">
          {/* Map area — full width */}
          <div className="flex-1 flex flex-col min-h-0">
            {elevation ? (
              <>
                <div className="flex-1 min-h-0">
                  <MapViewer
                    metadata={meta ?? null}
                    elevation={elevation}
                    voronoiCells={voronoiCells}
                    cvtMesh={cvtMesh}
                    layers={layerState.layers}

                    onCursorMove={setCursor}
                    onCellHover={handleCellHover}
                    onCellClick={selectCell}
                    hoveredCell={cleanMode ? null : hoveredCell}
                    selectedCells={cleanMode ? emptySelection : selectedCells}
                    sunLongitudeDeg={sunLongitudeDeg}
                    solarDeclinationDeg={solarDeclination}
                    dayNight={dayNightEnabled}
                    monthlyTemperature={monthlyField === 'temperature' ? monthlyThematic : null}
                    monthlyPrecipitation={monthlyField === 'precipitation' ? monthlyThematic : null}
                    monthlyPressure={monthlyField === 'pressure' ? monthlyThematic : null}
                    monthlyPressureError={monthlyField === 'pressureError' ? monthlyThematic : null}
                    monthlySlp={monthlyField === 'slp' ? monthlyThematic : null}
                    uccTexture={uccTexture}
                    monthlyWindEast={monthlyMode ? monthlyData?.windEastMonthly ?? null : null}
                    monthlyWindNorth={monthlyMode ? monthlyData?.windNorthMonthly ?? null : null}
                    month={monthlyMonth}
                    showGraticule={!cleanMode}
                    onZoomChange={setDisplayZoom}
                    onViewStateChange={setViewState}
                  />
                </div>
                {!cleanMode && (
                  <MobileCellCard
                    cell={selectedCells.size === 1 ? selectedCellData : null}
                    cursor={cursor}
                    onClose={clearSelection}
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

          {/* Floating toggle button (mobile only, visible when drawer closed) */}
          {!cleanMode && !leftPanelOpen && (
            <button
              onClick={() => setLeftPanelOpen(true)}
              className="absolute bottom-4 left-4 z-30 w-10 h-10 rounded-full bg-space-panel border border-space-border flex items-center justify-center text-gray-400 hover:text-neon-cyan hover:border-neon-cyan/40 shadow-lg"
              title={t('label.layerSettings')}
            >
              ☰
            </button>
          )}

          {/* Left panel drawer overlay */}
          {!cleanMode && leftPanelOpen && (
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
                {platesError && selectedPlanet && (
                  <div className="text-xs text-gray-500 pt-2">
                    {t('msg.noPlateData')}
                  </div>
                )}
                <div className="pt-3 border-t border-space-border">
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

        {/* === Desktop layout (≥ md, hidden by default) === */}
        <div className="hidden md:flex flex-1 min-h-0">
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
            {platesError && selectedPlanet && (
              <div className="text-xs text-gray-500 pt-2">
                {t('msg.noPlateData')}
              </div>
            )}
            <div className="pt-3 border-t border-space-border">
              <SunControl
                sunLongitudeDeg={sunLongitudeDeg}
                onLongitudeChange={setSunLongitudeDeg}
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
                    voronoiCells={voronoiCells}
                    cvtMesh={cvtMesh}
                    layers={layerState.layers}

                    onCursorMove={setCursor}
                    onCellHover={handleCellHover}
                    onCellClick={selectCell}
                    hoveredCell={cleanMode ? null : hoveredCell}
                    selectedCells={cleanMode ? emptySelection : selectedCells}
                    sunLongitudeDeg={sunLongitudeDeg}
                    solarDeclinationDeg={solarDeclination}
                    dayNight={dayNightEnabled}
                    monthlyTemperature={monthlyField === 'temperature' ? monthlyThematic : null}
                    monthlyPrecipitation={monthlyField === 'precipitation' ? monthlyThematic : null}
                    monthlyPressure={monthlyField === 'pressure' ? monthlyThematic : null}
                    monthlyPressureError={monthlyField === 'pressureError' ? monthlyThematic : null}
                    monthlySlp={monthlyField === 'slp' ? monthlyThematic : null}
                    uccTexture={uccTexture}
                    monthlyWindEast={monthlyMode ? monthlyData?.windEastMonthly ?? null : null}
                    monthlyWindNorth={monthlyMode ? monthlyData?.windNorthMonthly ?? null : null}
                    month={monthlyMonth}
                    showGraticule={!cleanMode}
                    onZoomChange={setDisplayZoom}
                    onViewStateChange={setViewState}
                  />

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
                    <MapLegend visible={activeMainLayer === 'terrain' || activeMainLayer === 'landsea'} />
                  )}
                </div>
                {!cleanMode && (
                  <MapStatusBar cursor={cursor} zoom={displayZoom} hoveredCell={hoveredCellData} />
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
          <div className="w-52 shrink-0 bg-space-panel/50 border-l border-space-border flex flex-col min-h-0">
            {/* Scrollable inspector area */}
            <div className="flex-1 min-h-0 overflow-y-auto p-3">
              <MapCellInspector
                cell={inspectorCell}
                cvtMesh={cvtMesh}
                planetName={currentPlanetName}
                selectedCells={selectedCellObjects}
                activeColorMode={vs.activeColorMode}
                monthlyMode={monthlyMode}
                monthIndex={monthlyMonth}
                monthlyData={monthlyData}
                yearlyData={yearlyData}
                isEarth={worldName === 'earth'}
              />
              {selectedCells.size > 1 && (
                <p className="text-[10px] text-gray-600 mt-2 text-center">
                  {t('msg.escClearSelection')}
                </p>
              )}
            </div>

            {/* Minimap — pinned at bottom */}
            {elevation && (
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
            )}
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
