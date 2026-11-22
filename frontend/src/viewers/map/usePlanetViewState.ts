/**
 * usePlanetViewState — the shared view state of the 2D map page and the 3D
 * globe page.
 *
 * Both pages view the same planet data (meta / elevation / CVT mesh / monthly
 * climate) with the same URL-driven posture (?branch, ?layer, ?clean, ?month,
 * ?sun=&season=&night=), the same layer/time/sun panels, and the same
 * cell-selection semantics.  Before this hook existed each page carried a
 * ~500-line parallel copy of that wiring — every new layer or climate feature
 * had to be landed twice.  The pages now own only what genuinely differs:
 * the 2D renderer (Three.js plane + SVG overlay + minimap) versus the 3D
 * renderer (R3F sphere + orbit controls + spin + stellar transition).
 *
 * The hook is instantiated once per page; all effects use their cleanup paths
 * so React StrictMode double-mounting is safe.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import type { ImportElevationResult } from '../../components/map/ImportElevationButton'
import type { ImportedState } from '../../api/elevationImport'
import type { TemperatureOrigin } from '../../playground/temperatureDraft'
import { saveLastWorld } from '../../utils/lastWorld'
import { tutorialMilestone } from '../../tutorial/tutorialProgress'
import { initialLayerState, activeMainLayerId, inspectionLayerId } from '../../components/map/layerStateInit'
import type { LayerState, MapLayerDetail } from '../../components/map/MapLayerPanel'
import { decodePngToFloat32 } from './utils/imageCodec'
import { readElevationPng } from '../packs/elevationRaster'
import { hasOriginalTerrain, meshTextureDimensions, terrainSourceFor, type TerrainSource } from './elevationSource'
import { solarDeclinationDeg } from '../utils/solar'
import useCellIdMap from './useCellIdMap'
import { useMonthlyClimate } from './useMonthlyClimate'
import { isScalarLayer } from './scalarLayers'
import { useKoppenDownscale } from './useKoppenDownscale'
import { koppenProductFor } from './observedKoppen'
import { useObservedKoppen } from './useObservedKoppen'
import { isMonthlyLayer, monthFromSearch } from '../../components/map/climateTime'
import { useYearlyClimate } from './useYearlyClimate'
import { useUccLayer } from './useUccLayer'
import type { EbmMapView } from './useTemperatureTrialPreview'
import type { ColorMode, CVTMesh, MapMetadata, VoronoiCell } from './types'

/** The two pages this hook serves — decides the planet-redirect URL base. */
export type PlanetViewKind = 'map' | 'globe'
const EMPTY_ELEVATION_DIMENSIONS = { w: 0, h: 0 }
type ImportMessage = { ok: boolean; text: string; temperatureOrigin?: TemperatureOrigin }

export interface PlanetViewState {
  // --- URL-derived posture (shared across 2D↔3D navigation) ---
  selectedBranch: string | null
  cleanMode: boolean
  setCleanMode: (v: boolean) => void

  // --- Layer state (?layer= deep link + slot semantics) ---
  layerState: LayerState
  setLayerState: (next: LayerState) => void
  activeMainLayer: string | null
  activeColorMode: ColorMode | null

  // --- Monthly climate mode (Phase 4 / tech debt 24) ---
  monthlyMode: boolean
  handleMonthlyModeChange: (mode: boolean) => void
  selectMonth: (index: number) => void
  displayingMonthly: boolean
  layerDetail: (available: ReadonlySet<ColorMode>, trialTemperature: boolean) => MapLayerDetail | undefined

  // --- Particle-flow display for wind / ocean-current layers (?particles=1) ---
  particleMode: boolean
  setParticleMode: (v: boolean) => void

  // --- Lighting (?sun=&season=&night=, shared with the other view) ---
  sunLongitudeDeg: number
  setSunLongitudeDeg: React.Dispatch<React.SetStateAction<number>>
  seasonDeg: number
  setSeasonDeg: React.Dispatch<React.SetStateAction<number>>
  dayNightEnabled: boolean
  setDayNightEnabled: (v: boolean) => void
  solarDeclination: number

  // --- Planet identity + catalogs ---
  selectedPlanet: string
  mapPlanets: string[] | undefined
  meta: MapMetadata | undefined
  bodyByName: Map<string, any>
  /** Planet radius in metres (from the catalog; Earth radius when unknown). */
  planetRadiusM: number
  currentPlanetName: string | null
  axialTiltDeg: number
  worldPlanetsError: boolean
  platesError: boolean
  metaError: boolean
  elevError: boolean
  cvtMeshError: boolean
  /** The map has a stored heightmap but no mesh yet (imported, not built). */
  awaitingBuild: boolean

  // --- Raster + mesh data ---
  elevation: Float32Array | null
  elevationDims: { w: number; h: number }
  terrainSource: TerrainSource
  setTerrainSource: (source: TerrainSource) => void
  canSelectTerrainSource: boolean
  meshTextureSize: { width: number; height: number }
  cvtMesh: CVTMesh | null
  voronoiCells: VoronoiCell[]
  cellIdMap: ReturnType<typeof useCellIdMap>

  // --- Monthly/UCC climate products ---
  scalarThematic: ReturnType<typeof useMonthlyClimate>['texture']
  koppenTexture: ReturnType<typeof useKoppenDownscale>['texture']
  monthlyData: ReturnType<typeof useMonthlyClimate>['data']
  monthlyLoading: boolean
  monthlyMonth: number
  yearlyData: ReturnType<typeof useYearlyClimate>
  uccTexture: ReturnType<typeof useUccLayer>

  // --- Cursor + cell selection (panel state machine) ---
  cursor: { lon: number; lat: number; elevation: number; elevationM: number; pixelX: number; pixelY: number } | null
  setCursor: React.Dispatch<React.SetStateAction<PlanetViewState['cursor']>>
  hoveredCell: number | null
  /** Hover setter that also remembers the last hovered cell (inspector retention). */
  handleCellHover: (cellId: number | null) => void
  lastCell: number | null
  selectedCells: Set<number>
  /** Shared selection semantics: Ctrl = toggle-in-place, plain = replace. */
  selectCell: (cellId: number, ctrlKey: boolean) => void
  clearSelection: () => void
  selectedCellData: VoronoiCell | null
  hoveredCellData: VoronoiCell | null
  inspectorCell: VoronoiCell | null
  selectedCellObjects: VoronoiCell[] | undefined

  // --- Heightmap / geography import (live mode write ops) ---
  importMsg: ImportMessage | null
  setImportMsg: React.Dispatch<React.SetStateAction<ImportMessage | null>>
  handleImported: (r: ImportElevationResult) => void
}

export function usePlanetViewState(
  worldName: string | undefined,
  /** Planet ID from the route (optional segment on /map, mandatory on /globe). */
  routePlanetId: string | undefined,
  viewKind: PlanetViewKind,
  trialActive = false,
  ebm?: EbmMapView | null,
): PlanetViewState {
  const { t } = useTranslation('map')
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  // --- Branch (?branch=) — derived from the URL so browser back/forward works ---
  const selectedBranch = searchParams.get('branch') || null

  // --- Clean view (?clean=1): hide every piece of UI for recording ---
  const cleanMode = searchParams.get('clean') === '1'
  const setCleanMode = (v: boolean) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (v) next.set('clean', '1')
      else next.delete('clean')
      return next
    }, { replace: true })
  }

  // --- Layers (?layer= deep link, slot semantics identical to panel clicks) ---
  const [officialLayers, setOfficialLayers] = useState<LayerState>(() =>
    initialLayerState(searchParams.get('layer'), worldName === 'earth'))
  const layerState = ebm?.layers ?? officialLayers
  const setLayerState = ebm?.setLayers ?? setOfficialLayers
  const activeMainLayer = activeMainLayerId(layerState)
  const officialMainLayer = activeMainLayerId(officialLayers)
  useEffect(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (officialMainLayer && officialMainLayer !== 'terrain') next.set('layer', officialMainLayer)
      else next.delete('layer')
      return next
    }, { replace: true })
  }, [officialMainLayer, setSearchParams])

  const [officialMonthlyMode, setOfficialMonthlyMode] = useState(
    () => searchParams.get('monthly') === '1' || searchParams.get('play') === '1',
  )
  const [officialMonth, setOfficialMonth] = useState(() => monthFromSearch(searchParams))
  const monthlyMode = ebm?.time.monthly ?? officialMonthlyMode
  const monthlyMonth = ebm?.time.month ?? officialMonth
  const setTrialTime = ebm?.setTime
  const handleMonthlyModeChange = useCallback((monthly: boolean) => {
    if (setTrialTime) setTrialTime({ monthly, month: monthlyMonth })
    else setOfficialMonthlyMode(monthly)
    if (monthly && worldName) tutorialMilestone({ type: 'monthly', world: worldName })
  }, [setTrialTime, monthlyMonth, worldName])
  const selectMonth = useCallback((index: number) => {
    if (setTrialTime) setTrialTime({ monthly: true, month: index })
    else {
      setOfficialMonth(index)
      setOfficialMonthlyMode(true)
    }
  }, [setTrialTime])
  const downscale = searchParams.get('detail') === 'downscaled'
  const setDownscale = useCallback((enabled: boolean) => {
    setSearchParams(previous => {
      const next = new URLSearchParams(previous)
      if (enabled) next.set('detail', 'downscaled')
      else next.delete('detail')
      return next
    }, { replace: true })
  }, [setSearchParams])
  const observedDetail = searchParams.get('koppenDetail') === 'observed'
  const setObservedDetail = useCallback((enabled: boolean) => {
    setSearchParams(previous => {
      const next = new URLSearchParams(previous)
      if (enabled) next.set('koppenDetail', 'observed')
      else next.delete('koppenDetail')
      return next
    }, { replace: true })
  }, [setSearchParams])

  // --- Particle-flow display (wind / current layers) ---
  // URL-backed so the 2D↔3D switch and shared links keep the display style.
  const particleMode = searchParams.get('particles') === '1'
  const setParticleMode = useCallback((v: boolean) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (v) next.set('particles', '1')
      else next.delete('particles')
      return next
    }, { replace: true })
  }, [setSearchParams])

  const activeColorMode = inspectionLayerId(layerState)

  // --- Cursor + cell selection state ---
  const [cursor, setCursor] = useState<PlanetViewState['cursor']>(null)
  const [hoveredCell, setHoveredCell] = useState<number | null>(null)
  /** Last hovered cell — retained so the inspector doesn't reset on mouse-leave. */
  const [lastCell, setLastCell] = useState<number | null>(null)
  const [selectedCells, setSelectedCells] = useState<Set<number>>(new Set())

  const handleCellHover = useCallback((cellId: number | null) => {
    setHoveredCell(cellId)
    if (cellId !== null) setLastCell(cellId)
  }, [])

  /** Shared selection semantics (2D and 3D): Ctrl+click toggles in place,
   * plain click replaces the selection. */
  const selectCell = useCallback((cellId: number, ctrlKey: boolean) => {
    setSelectedCells((prev) => {
      const alreadySelected = prev.has(cellId)
      if (ctrlKey) {
        const next = new Set(prev)
        if (alreadySelected) next.delete(cellId)
        else next.add(cellId)
        return next
      }
      if (alreadySelected && prev.size === 1) return new Set()
      return new Set([cellId])
    })
  }, [])

  const clearSelection = useCallback(() => setSelectedCells(new Set()), [])

  // --- Planet catalogs ---
  const { data: mapPlanets } = useQuery({
    queryKey: ['mapPlanets', worldName, selectedBranch],
    queryFn: () => api.listMapPlanets(worldName!, selectedBranch),
    enabled: !!worldName,
  })
  const { data: worldPlanets, isError: worldPlanetsError } = useQuery({
    queryKey: ['worldPlanets', worldName, selectedBranch],
    queryFn: () => api.getPlanets(worldName!, selectedBranch),
    enabled: !!worldName,
    retry: false,
  })
  // Stellar system catalog — satellites (satellite_moon, satellite_titan, …)
  // live only here, not in the geological planets catalog. Needed for body
  // names and axial tilt of every mapped body (solar-system reference bodies
  // inside the earth anchor world have no planets.yaml entries).
  const { data: stellarSystem } = useQuery({
    queryKey: ['astronomy', worldName, selectedBranch],
    queryFn: () => api.getStellarSystem(worldName!, selectedBranch),
    enabled: !!worldName,
    retry: false,
  })
  const bodyByName = useMemo(() => {
    const m = new Map<string, any>()
    for (const b of stellarSystem?.bodies ?? []) if (b?.id) m.set(b.id, b)
    for (const p of worldPlanets ?? []) if (p?.id) m.set(p.id, { ...m.get(p.id), ...p })
    return m
  }, [stellarSystem, worldPlanets])

  // --- Planet selection reconciliation ---
  const selectedPlanet = routePlanetId ?? mapPlanets?.[0] ?? worldPlanets?.[0]?.id ?? ''
  const savedRoute = !isStaticMode() && searchParams.has('climateResult')
  useEffect(() => {
    if (!savedRoute && mapPlanets?.length && (!routePlanetId || !mapPlanets.includes(routePlanetId))) {
      const qs = searchParams.toString()
      navigate(`/worlds/${worldName}/${viewKind}/${mapPlanets[0]}${qs ? `?${qs}` : ''}`, {
        replace: true,
      })
    }
  }, [mapPlanets, routePlanetId, navigate, worldName, searchParams, viewKind, savedRoute])

  // --- Map data queries ---
  const saved = ebm?.result.saved
  const useOfficialMap = !(savedRoute && (saved || trialActive))
  const { data: formalMeta, isError: formalMetaError } = useQuery({
    queryKey: ['mapMeta', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getMapMeta(worldName!, selectedPlanet, selectedBranch),
    enabled: useOfficialMap && !!worldName && !!selectedPlanet,
  })

  const { data: formalElevation, isError: formalElevationError } = useQuery({
    queryKey: ['elevationBlob', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getElevationBlob(worldName!, selectedPlanet, selectedBranch),
    enabled: useOfficialMap && !!worldName && !!selectedPlanet,
    retry: false,
  })
  const meta = saved?.metadata.surface ?? (useOfficialMap ? formalMeta : undefined)
  const elevationBlob = saved?.elevation ?? (useOfficialMap ? formalElevation : undefined)
  const metaError = useOfficialMap && formalMetaError
  const elevError = useOfficialMap && formalElevationError

  // Decode the elevation PNG once per blob — both pages render from the same
  // Float32Array; the 3D texture bake also needs the decoded dimensions.
  const importedElevation = Boolean(meta?.elevation_import)
  const originalTerrain = hasOriginalTerrain(meta)
  const [decoded, setDecoded] = useState<{ blob: Blob; original: boolean; data: Float32Array; w: number; h: number } | null>(null)
  const currentElevation = decoded?.blob === elevationBlob && decoded?.original === originalTerrain ? decoded : null
  const elevation = currentElevation?.data ?? null
  const elevationDims = currentElevation ?? EMPTY_ELEVATION_DIMENSIONS
  useEffect(() => {
    if (!elevationBlob) return
    let cancelled = false
    const decode = originalTerrain
      ? readElevationPng(elevationBlob, 0, 1).then(({ values, width, height }) => ({ data: values, width, height }))
      : decodePngToFloat32(elevationBlob)
    decode.then(({ data, width, height }) => {
      if (!cancelled) {
        setDecoded({ blob: elevationBlob, original: originalTerrain, data, w: width, h: height })
      }
    }).catch(() => {
      // Decode failure (e.g. corrupted PNG) → treat as no data
      if (!cancelled) setDecoded(null)
    })
    return () => { cancelled = true }
  }, [elevationBlob, originalTerrain])

  const { isError: officialPlatesError } = useQuery({
    queryKey: ['plates', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getPlates(worldName!, selectedPlanet, selectedBranch),
    enabled: useOfficialMap && !!worldName && !!selectedPlanet,
    retry: false,
  })

  // CVT mesh data for polygon rendering + cell lookups
  const meshNotBuilt = formalMeta?.voronoi_num_cells === 0
  const { data: officialMesh, isError: officialMeshError } = useQuery({
    queryKey: ['cvtMesh', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getCvtMesh(worldName!, selectedPlanet, selectedBranch),
    enabled: useOfficialMap && !!worldName && !!selectedPlanet && !!formalMeta && !meshNotBuilt,
    retry: false,
  })
  const platesError = useOfficialMap && officialPlatesError
  const cvtMeshError = !ebm && useOfficialMap && officialMeshError
  const cvtMesh = ebm?.result.mesh ?? (useOfficialMap ? officialMesh : undefined)
  // (cvtMeshError is re-declared from the query for the page error banner.)

  // Legacy voronoi fallback — fetched only when the CVT mesh is unavailable
  // (query failed or returned null). The mesh's `cells` carry the same data
  // with a richer property set; on a normal load this endpoint (a ~219 MB
  // JSON synthesized server-side per request) would be pure waste.
  const { data: voronoi } = useQuery({
    queryKey: ['voronoi', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getVoronoi(worldName!, selectedPlanet, selectedBranch),
    enabled: !!worldName && !!selectedPlanet && (cvtMeshError || cvtMesh === null),
    retry: false,
  })

  const voronoiCells: VoronoiCell[] = useMemo(
    () => cvtMesh?.cells ?? voronoi?.cells ?? [],
    [cvtMesh, voronoi],
  )

  const meshTextureSize = meshTextureDimensions(meta)
  const cellIdMap = useCellIdMap({ cvtMesh: cvtMesh ?? null, ...meshTextureSize })
  const hasMesh = Boolean(cvtMesh?.cells.length)
  const terrainSource = terrainSourceFor(meta, hasMesh, !!elevation, searchParams.get('terrain'))
  const canSelectTerrainSource = originalTerrain && !!elevation && hasMesh
  const setTerrainSource = (source: TerrainSource) => setSearchParams((prev) => {
    const next = new URLSearchParams(prev)
    if (source === 'raster') next.delete('terrain')
    else next.set('terrain', source)
    return next
  })

  // --- Lighting (?sun=&season=&night=) ---
  const [sunLongitudeDeg, setSunLongitudeDeg] = useState(() => {
    const v = Number(searchParams.get('sun'))
    return Number.isFinite(v) ? v : 0
  })
  const [seasonDeg, setSeasonDeg] = useState(() => {
    const v = Number(searchParams.get('season'))
    return Number.isFinite(v) ? v : 0
  })
  const [dayNightEnabled, setDayNightEnabled] = useState(() => searchParams.get('night') === '1')

  // --- Monthly/UCC climate products ---
  const seaLevelM = meta?.sea_level_m ?? 0
  const native = useMemo(() => importedElevation && elevation && meta && elevation.length === elevationDims.w * elevationDims.h ? {
    elevation, width: elevationDims.w, height: elevationDims.h, minM: meta.elevation_min_m, maxM: meta.elevation_max_m, seaLevelM,
  } : null, [importedElevation, elevation, meta, elevationDims, seaLevelM])
  const koppenActive = !trialActive && activeMainLayer === 'koppen'
  const legacyObservation = worldName === 'earth' && selectedPlanet === 'planet_earth' && !selectedBranch &&
    formalMeta?.pipeline_version === 'etopo1-import'
  const koppenProduct = koppenProductFor(formalMeta?.koppen, legacyObservation, !!ebm)
  const observedRaster = koppenActive && koppenProduct.source === 'observed' && koppenProduct.raster
  const observedKoppen = useObservedKoppen(worldName, selectedPlanet, selectedBranch, observedRaster && observedDetail)
  const { texture: scalarThematic, data: monthlyData, loading: monthlyLoading, displayingMonthly } = useMonthlyClimate({
    worldName, planetId: selectedPlanet, branch: selectedBranch, month: monthlyMonth,
    trialData: ebm?.result.monthly,
    field: !trialActive && isScalarLayer(activeMainLayer) ? activeMainLayer : null,
    active: !trialActive && (koppenActive || monthlyMode || isMonthlyLayer(activeColorMode)),
    monthlyMode, downscale, native, seaLevelM,
    cvtMesh: cvtMesh ?? null, cellIdMap,
    ...meshTextureSize, flipHorizontal: false,
  })
  const koppenDownscale = useKoppenDownscale(koppenActive && koppenProduct.source === 'model' && koppenProduct.same_grid_monthly,
    downscale, monthlyData, cvtMesh ?? null, cellIdMap,
    meshTextureSize.width, meshTextureSize.height, seaLevelM, native)
  const koppenTexture = observedKoppen.texture ?? koppenDownscale.texture
  const layerDetail: PlanetViewState['layerDetail'] = (available, trialTemperature) => {
    if (koppenActive && koppenProduct.source === 'observed') {
      return available.has('koppen') ? {
        observed: true, downscaled: observedRaster && observedDetail && !observedKoppen.failed,
        available: observedRaster, pending: observedKoppen.pending, failed: observedKoppen.failed, onChange: setObservedDetail,
      } : undefined
    }
    return {
      downscaled: downscale, onChange: setDownscale, pending: koppenDownscale.pending,
      available: trialActive ? trialTemperature : koppenDownscale.available ||
        (Boolean(cvtMesh) && isScalarLayer(activeMainLayer) && available.has(activeMainLayer)),
    }
  }
  const officialYearly = useYearlyClimate(ebm || !useOfficialMap ? undefined : worldName, selectedPlanet, selectedBranch)
  const yearlyProduct = ebm ? ebm.result.yearly : officialYearly
  const yearlyData = yearlyProduct && cvtMesh && yearlyProduct.numCells === cvtMesh.cells.length ? yearlyProduct : null
  const uccTexture = useUccLayer(
    yearlyData, cvtMesh ?? null, cellIdMap,
    meshTextureSize.width, meshTextureSize.height, false,
  )

  useEffect(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (sunLongitudeDeg !== 0) next.set('sun', String(sunLongitudeDeg))
      else next.delete('sun')
      if (seasonDeg !== 0) next.set('season', String(seasonDeg))
      else next.delete('season')
      if (dayNightEnabled) next.set('night', '1')
      else next.delete('night')
      if (officialMonthlyMode) next.set('monthly', '1')
      else next.delete('monthly')
      if (officialMonthlyMode || officialMonth !== 0) next.set('month', String(officialMonth))
      else next.delete('month')
      next.delete('play')
      return next
    }, { replace: true })
  }, [sunLongitudeDeg, seasonDeg, dayNightEnabled, officialMonthlyMode, officialMonth, setSearchParams])

  // Esc → exit clean mode first, otherwise clear all selections
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (searchParams.get('clean') === '1') {
        setSearchParams((prev) => {
          const next = new URLSearchParams(prev)
          next.delete('clean')
          return next
        }, { replace: true })
        return
      }
      setSelectedCells(new Set())
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [searchParams, setSearchParams])

  // --- Panel state machine ---
  // 0 selected → show hovered cell (null when mouse leaves → planet summary)
  // 1 selected → show that cell (locked, survives mouse leave)
  // >1 selected → show aggregate stats
  const selectedCellData = useMemo(() => {
    if (selectedCells.size === 0) return null
    const id = [...selectedCells][0]
    return voronoiCells.find((c) => c.id === id) ?? null
  }, [voronoiCells, selectedCells])

  const hoveredCellData = useMemo(() => {
    if (hoveredCell === null) return null
    return voronoiCells.find((c) => c.id === hoveredCell) ?? null
  }, [voronoiCells, hoveredCell])

  const lastCellData = useMemo(() => {
    if (lastCell === null) return null
    return voronoiCells.find((c) => c.id === lastCell) ?? null
  }, [voronoiCells, lastCell])

  const inspectorCell = selectedCells.size === 1
    ? selectedCellData
    : selectedCells.size > 1
      ? null  // triggers MultiCellStats
      : lastCellData

  const selectedCellObjects = useMemo(() => {
    if (selectedCells.size === 0) return undefined
    return [...selectedCells].map((id) => voronoiCells.find((c) => c.id === id)).filter(Boolean) as VoronoiCell[]
  }, [voronoiCells, selectedCells])

  // --- Display name / axial tilt / declination ---
  const currentPlanetName = useMemo(() => {
    if (!selectedPlanet) return null
    return bodyByName.get(selectedPlanet)?.name ?? null
  }, [selectedPlanet, bodyByName])
  // Catalog `radius` is in Earth radii (e.g. Nacrea 1.07); the particle
  // integrator converts m/s to degrees with the planet's own circumference.
  const planetRadiusM = useMemo(() => {
    if (saved) return saved.metadata.inputs.radius_km * 1000
    const r = bodyByName.get(selectedPlanet)?.radius
    return (typeof r === 'number' && r > 0 ? r : 1) * 6_371_000
  }, [selectedPlanet, bodyByName, saved])
  const axialTiltDeg = useMemo(() => {
    if (ebm) return ebm.result.forcing.axial_tilt_deg
    if (!selectedPlanet) return 0
    return bodyByName.get(selectedPlanet)?.axial_tilt_deg ?? 0
  }, [selectedPlanet, bodyByName, ebm])
  const solarDeclination = solarDeclinationDeg(seasonDeg, axialTiltDeg)

  // --- Heightmap import (write op; live mode only) ---
  const queryClient = useQueryClient()
  const [importMsg, setImportMsg] = useState<ImportMessage | null>(null)
  const handleImported = useCallback(
    (r: ImportElevationResult) => {
      for (const key of ['elevationBlob', 'voronoi', 'cvtMesh', 'plates', 'mapMeta']) {
        queryClient.invalidateQueries({
          queryKey: [key, worldName, selectedPlanet, selectedBranch],
        })
      }
      const res = t('msg.outputResolution', { w: r.output_resolution[0], h: r.output_resolution[1] })
      const stale = r.stale_layers?.length
        ? t('msg.staleLayers', { layers: r.stale_layers.join(t('msg.listSeparator')) })
        : ''
      setImportMsg({
        ok: true,
        temperatureOrigin: worldName && selectedPlanet ? { world: worldName, planet: selectedPlanet, branch: selectedBranch } : undefined,
        text: t('msg.importedHeightmap', {
          format: r.source_format,
          resolution: res,
          land: `${(r.land_area_fraction * 100).toFixed(1)}%`,
          stale: stale,
        }),
      })
    },
    [queryClient, worldName, selectedPlanet, selectedBranch],
  )

  // A finished import journey hands its result over in router state; show it
  // once, then drop the state so a refresh does not repeat the banner.
  const location = useLocation()
  useEffect(() => {
    const imported = (location.state as ImportedState | null)?.imported
    if (!imported || imported.world !== worldName) return
    handleImported(imported.result)
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null })
  }, [location.state, location.pathname, location.search, worldName, handleImported, navigate])

  // Remember where the author was, so the home page can offer to return.
  useEffect(() => {
    if (!worldName || !selectedPlanet) return
    saveLastWorld({
      world: worldName,
      planetId: selectedPlanet,
      branch: selectedBranch,
      path: `${location.pathname}${location.search}`,
    })
  }, [worldName, selectedPlanet, selectedBranch, location.pathname, location.search])

  return {
    selectedBranch,
    cleanMode, setCleanMode,
    layerState, setLayerState, activeMainLayer, activeColorMode,
    monthlyMode, handleMonthlyModeChange, selectMonth, displayingMonthly, layerDetail,
    particleMode, setParticleMode,
    sunLongitudeDeg, setSunLongitudeDeg, seasonDeg, setSeasonDeg,
    dayNightEnabled, setDayNightEnabled, solarDeclination,
    selectedPlanet, mapPlanets, meta, metaError, elevError, cvtMeshError,
    awaitingBuild: !ebm && useOfficialMap && !!elevation && meshNotBuilt,
    bodyByName, currentPlanetName, planetRadiusM, axialTiltDeg,
    worldPlanetsError, platesError,
    elevation, elevationDims, terrainSource, setTerrainSource, canSelectTerrainSource, meshTextureSize,
    cvtMesh: cvtMesh ?? null, voronoiCells, cellIdMap,
    scalarThematic, koppenTexture, monthlyData, monthlyLoading, monthlyMonth, yearlyData, uccTexture,
    cursor, setCursor, hoveredCell, handleCellHover, lastCell, selectedCells,
    selectCell, clearSelection,
    selectedCellData, hoveredCellData, inspectorCell, selectedCellObjects,
    importMsg, setImportMsg, handleImported,
  }
}
