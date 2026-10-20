/**
 * usePlanetViewState — the shared view state of the 2D map page and the 3D
 * globe page.
 *
 * Both pages view the same planet data (meta / elevation / CVT mesh / monthly
 * climate) with the same URL-driven posture (?branch, ?layer, ?clean, ?play,
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

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import type { ImportElevationResult } from '../../components/map/ImportElevationButton'
import { LAYER_HELP } from '../../components/map/helpContent'
import { initialLayerState, activeMainLayerId } from '../../components/map/layerStateInit'
import type { LayerState } from '../../components/map/MapLayerPanel'
import { decodePngToFloat32 } from './utils/imageCodec'
import { solarDeclinationDeg } from '../utils/solar'
import useCellIdMap from './useCellIdMap'
import { useMonthlyClimate, type MonthlyField } from './useMonthlyClimate'
import { useSeasonTimelapse } from './useSeasonTimelapse'
import { useYearlyClimate } from './useYearlyClimate'
import { useUccLayer } from './useUccLayer'
import type { ColorMode, CVTMesh, MapMetadata, VoronoiCell } from './types'

/** The two pages this hook serves — decides the planet-redirect URL base. */
export type PlanetViewKind = 'map' | 'globe'

export interface PlanetViewState {
  // --- URL-derived posture (shared across 2D↔3D navigation) ---
  selectedBranch: string | null
  setSelectedBranch: (branch: string | null) => void
  cleanMode: boolean
  setCleanMode: (v: boolean) => void

  // --- Seasonal cycle playback (?play=1) ---
  timelapsePlaying: boolean
  setTimelapsePlaying: (v: boolean) => void
  monthMs: number
  setMonthMs: (v: number) => void
  sunSweep: boolean
  setSunSweep: (v: boolean) => void
  sweeping: boolean

  // --- Layer state (?layer= deep link + slot semantics) ---
  layerState: LayerState
  setLayerState: React.Dispatch<React.SetStateAction<LayerState>>
  activeMainLayer: string | null
  activeColorMode: ColorMode | null

  // --- Monthly climate mode (Phase 4 / tech debt 24) ---
  monthlyMode: boolean
  handleMonthlyModeChange: (mode: boolean) => void
  monthlyField: MonthlyField | null
  monthlyActive: boolean

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
  currentPlanetName: string | null
  axialTiltDeg: number
  worldPlanetsError: boolean
  platesError: boolean
  metaError: boolean
  elevError: boolean
  cvtMeshError: boolean

  // --- Raster + mesh data ---
  elevation: Float32Array | null
  elevationDims: { w: number; h: number }
  cvtMesh: CVTMesh | null
  voronoiCells: VoronoiCell[]
  cellIdMap: ReturnType<typeof useCellIdMap>

  // --- Monthly/UCC climate products ---
  monthlyThematic: ReturnType<typeof useMonthlyClimate>['texture']
  monthlyData: ReturnType<typeof useMonthlyClimate>['data']
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
  importMsg: { ok: boolean; text: string } | null
  setImportMsg: React.Dispatch<React.SetStateAction<{ ok: boolean; text: string } | null>>
  handleImported: (r: ImportElevationResult) => void
}

export function usePlanetViewState(
  worldName: string | undefined,
  /** Planet ID from the route (optional segment on /map, mandatory on /globe). */
  routePlanetId: string | undefined,
  viewKind: PlanetViewKind,
): PlanetViewState {
  const { t } = useTranslation('map')
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  // --- Branch (?branch=) — derived from the URL so browser back/forward works ---
  const selectedBranch = searchParams.get('branch') || null
  const setSelectedBranch = (branch: string | null) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (branch) next.set('branch', branch)
      else next.delete('branch')
      return next
    }, { replace: true })
  }

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

  // --- Seasonal cycle playback (?play=1) ---
  const [timelapsePlaying, setTimelapsePlaying] = useState(() => searchParams.get('play') === '1')
  const [monthMs, setMonthMs] = useState(2000)
  const [sunSweep, setSunSweep] = useState(false)

  // --- Layers (?layer= deep link, slot semantics identical to panel clicks) ---
  const [layerState, setLayerState] = useState<LayerState>(() =>
    initialLayerState(searchParams.get('layer'), worldName === 'earth'))
  const activeMainLayer = activeMainLayerId(layerState)
  useEffect(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (activeMainLayer && activeMainLayer !== 'terrain') next.set('layer', activeMainLayer)
      else next.delete('layer')
      return next
    }, { replace: true })
  }, [activeMainLayer, setSearchParams])

  // --- Monthly climate mode (Phase 4): the active temperature/precipitation/
  // pressure layer shows monthly data driven by the season slider, and the wind
  // arrows switch to the monthly wind field (tech debt 24). ---
  const [monthlyMode, setMonthlyMode] = useState(false)
  const monthlyField: MonthlyField | null = monthlyMode
    ? layerState.layers.temperature > 0
      ? 'temperature'
      : layerState.layers.precipitation > 0
        ? 'precipitation'
        : layerState.layers.pressure > 0
          ? 'pressure'
          : layerState.layers.pressureError > 0
            ? 'pressureError'
            : layerState.layers.slp > 0
              ? 'slp'
              : null
    : null
  const monthlyActive = monthlyMode && (
    layerState.layers.temperature > 0 ||
    layerState.layers.precipitation > 0 ||
    layerState.layers.pressure > 0 ||
    layerState.layers.pressureError > 0 ||
    layerState.layers.slp > 0 ||
    layerState.layers.winds > 0
  )
  const handleMonthlyModeChange = (mode: boolean) => setMonthlyMode(mode)

  // --- Inspector auto-expand: track the most recently activated layer
  // (opacity 0 → >0) so eye-toggled overlays auto-expand their group too.
  // The default base (terrain) is always active, so a naive "prefer thematic"
  // would always pick terrain and never surface an overlay's group. ---
  const prevLayersRef = useRef(layerState.layers)
  const [lastActivated, setLastActivated] = useState<ColorMode | null>(null)
  useEffect(() => {
    const prev = prevLayersRef.current
    for (const [id, v] of Object.entries(layerState.layers)) {
      if (v > 0 && (prev[id as ColorMode] ?? 0) <= 0) {
        setLastActivated(id as ColorMode)
      }
    }
    prevLayersRef.current = layerState.layers
  }, [layerState])

  // Active layer for the inspector's auto-expand: the most recently activated
  // wins while still visible; otherwise the mutually-exclusive thematic layer,
  // then a toggle overlay.
  const activeColorMode = useMemo<ColorMode | null>(() => {
    if (lastActivated && (layerState.layers[lastActivated] ?? 0) > 0) return lastActivated
    const active = LAYER_HELP.filter((l) => (layerState.layers[l.id] ?? 0) > 0)
    const thematic = active.find((l) => l.kind === 'thematic' || l.kind === 'base')
    const overlay = active.find((l) => l.kind === 'fill' || l.kind === 'feature')
    return (thematic ?? overlay)?.id ?? null
  }, [layerState, lastActivated])

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
  // Mirror of the route: state initialised from the (optional) route segment,
  // redirected to the branch's first available map when the ID is stale
  // (map IDs differ per branch — climate-dev stores "planet_earth" while
  // terrain-dev stores "earth" — so a branch switch can leave a 404ing ID).
  const [selectedPlanet, setSelectedPlanet] = useState(routePlanetId ?? '')
  useEffect(() => {
    if (selectedPlanet && mapPlanets && mapPlanets.includes(selectedPlanet)) return
    if (selectedPlanet && !mapPlanets) return // list not loaded yet — wait

    if (mapPlanets && mapPlanets.length > 0) {
      const target = mapPlanets[0]
      setSelectedPlanet(target)
      const qs = searchParams.toString()
      navigate(`/worlds/${worldName}/${viewKind}/${target}${qs ? `?${qs}` : ''}`, {
        replace: true,
      })
      return
    }
    // No maps available anywhere — fall back to a defined planet ID (no map
    // to navigate to; the page shows its no-data state).
    if (!selectedPlanet && worldPlanets && worldPlanets.length > 0) {
      setSelectedPlanet(worldPlanets[0].id)
    }
  }, [mapPlanets, worldPlanets, selectedPlanet, navigate, worldName, searchParams, viewKind])

  // --- Map data queries ---
  const { data: meta, isError: metaError } = useQuery({
    queryKey: ['mapMeta', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getMapMeta(worldName!, selectedPlanet, selectedBranch),
    enabled: !!worldName && !!selectedPlanet,
  })

  const { data: elevationBlob, isError: elevError } = useQuery({
    queryKey: ['elevationBlob', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getElevationBlob(worldName!, selectedPlanet, selectedBranch),
    enabled: !!worldName && !!selectedPlanet,
    retry: false,
  })

  // Decode the elevation PNG once per blob — both pages render from the same
  // Float32Array; the 3D texture bake also needs the decoded dimensions.
  const [elevation, setElevation] = useState<Float32Array | null>(null)
  const [elevationDims, setElevationDims] = useState<{ w: number; h: number }>({ w: 0, h: 0 })
  useEffect(() => {
    if (!elevationBlob) {
      setElevation(null)
      return
    }
    let cancelled = false
    decodePngToFloat32(elevationBlob).then(({ data, width, height }) => {
      if (!cancelled) {
        setElevation(data)
        setElevationDims({ w: width, h: height })
      }
    }).catch(() => {
      // Decode failure (e.g. corrupted PNG) → treat as no data
      if (!cancelled) setElevation(null)
    })
    return () => { cancelled = true }
  }, [elevationBlob])

  const { isError: platesError } = useQuery({
    queryKey: ['plates', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getPlates(worldName!, selectedPlanet, selectedBranch),
    enabled: !!worldName && !!selectedPlanet,
    retry: false,
  })

  // CVT mesh data for polygon rendering + cell lookups
  const { data: cvtMesh, isError: cvtMeshError } = useQuery({
    queryKey: ['cvtMesh', worldName, selectedPlanet, selectedBranch],
    queryFn: () => api.getCvtMesh(worldName!, selectedPlanet, selectedBranch),
    enabled: !!worldName && !!selectedPlanet,
    retry: false,
  })
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

  const cellIdMap = useCellIdMap({
    cvtMesh: cvtMesh ?? null,
    width: meta?.width ?? 2048,
    height: meta?.height ?? 1024,
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
  const { texture: monthlyThematic, data: monthlyData, month: monthlyMonth } = useMonthlyClimate({
    worldName, planetId: selectedPlanet, branch: selectedBranch, seasonDeg,
    field: monthlyField, active: monthlyActive, playing: timelapsePlaying,
    cvtMesh: cvtMesh ?? null, cellIdMap,
    width: meta?.width ?? 2048, height: meta?.height ?? 1024, flipHorizontal: false,
  })
  const yearlyData = useYearlyClimate(worldName, selectedPlanet, selectedBranch)
  const uccTexture = useUccLayer(
    yearlyData, cvtMesh ?? null, cellIdMap,
    meta?.width ?? 2048, meta?.height ?? 1024, false,
  )

  const sweeping = timelapsePlaying && monthlyMode && sunSweep

  // Lighting URL sync, gated during a sun sweep (continuous rAF → one
  // history.replace on stop, not one per frame).  Keeping the params in the
  // URL means lighting is shareable and carries across 2D↔3D navigation.
  useEffect(() => {
    if (sweeping) return
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
  }, [sunLongitudeDeg, seasonDeg, dayNightEnabled, setSearchParams, sweeping])

  // Sun sweep: continuously rotate the subsolar longitude so the day/night
  // terminator sweeps across the planet — one full revolution per model year
  // (12 × monthMs), phase-locked with the month stepper.
  useEffect(() => {
    if (!sweeping) return
    let raf = 0
    let last = performance.now()
    const loop = (now: number) => {
      const dt = (now - last) / 1000
      last = now
      const yearSec = (monthMs * 12) / 1000
      setSunLongitudeDeg((v) => (v + (360 / yearSec) * dt) % 360)
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [sweeping, monthMs])

  // ?play=1 deep link: explicitly opt into monthly mode (a ~20 MB fetch the
  // user implicitly consents to by sharing/opening the link) and make sure a
  // monthly layer is visible — otherwise there is nothing to animate.
  useEffect(() => {
    if (searchParams.get('play') !== '1') return
    setMonthlyMode(true)
    setLayerState((prev) => {
      const L = prev.layers
      if (L.temperature > 0 || L.precipitation > 0 || L.pressure > 0 ||
          L.pressureError > 0 || L.slp > 0 || L.winds > 0) return prev
      return { layers: { ...L, temperature: 0.85 } }
    })
  }, [])

  // Month stepper: one discrete step per beat (same semantics as the slider,
  // so ?season= write-back stays at 12 hits per cycle).
  useSeasonTimelapse({
    playing: timelapsePlaying && monthlyMode,
    monthMs,
    seasonDeg,
    onSeasonChange: setSeasonDeg,
  })

  // Persist the play state (?play=1) so a deep link reopens in playing
  // posture; speed/sweep stay ephemeral UI state.
  useEffect(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (timelapsePlaying) next.set('play', '1')
      else next.delete('play')
      return next
    }, { replace: true })
  }, [timelapsePlaying, setSearchParams])

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
    if (selectedCells.size <= 1) return undefined
    return [...selectedCells].map((id) => voronoiCells.find((c) => c.id === id)).filter(Boolean) as VoronoiCell[]
  }, [voronoiCells, selectedCells])

  // --- Display name / axial tilt / declination ---
  const currentPlanetName = useMemo(() => {
    if (!selectedPlanet) return null
    return bodyByName.get(selectedPlanet)?.name ?? null
  }, [selectedPlanet, bodyByName])
  const axialTiltDeg = useMemo(() => {
    if (!selectedPlanet) return 0
    return bodyByName.get(selectedPlanet)?.axial_tilt_deg ?? 0
  }, [selectedPlanet, bodyByName])
  const solarDeclination = solarDeclinationDeg(seasonDeg, axialTiltDeg)

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
    [queryClient, worldName, selectedPlanet, selectedBranch],
  )

  return {
    selectedBranch, setSelectedBranch,
    cleanMode, setCleanMode,
    timelapsePlaying, setTimelapsePlaying, monthMs, setMonthMs, sunSweep, setSunSweep, sweeping,
    layerState, setLayerState, activeMainLayer, activeColorMode,
    monthlyMode, handleMonthlyModeChange, monthlyField, monthlyActive,
    sunLongitudeDeg, setSunLongitudeDeg, seasonDeg, setSeasonDeg,
    dayNightEnabled, setDayNightEnabled, solarDeclination,
    selectedPlanet, mapPlanets, meta, metaError, elevError, cvtMeshError,
    bodyByName, currentPlanetName, axialTiltDeg,
    worldPlanetsError, platesError,
    elevation, elevationDims, cvtMesh: cvtMesh ?? null, voronoiCells, cellIdMap,
    monthlyThematic, monthlyData, monthlyMonth, yearlyData, uccTexture,
    cursor, setCursor, hoveredCell, handleCellHover, lastCell, selectedCells,
    selectCell, clearSelection,
    selectedCellData, hoveredCellData, inspectorCell, selectedCellObjects,
    importMsg, setImportMsg, handleImported,
  }
}
