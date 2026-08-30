/**
 * MapCellInspector — three-mode right panel.
 *
 * Mode A (no cell, 0 selected): Planet summary card with stats from cvtMesh.
 * Mode B (cell selected): Full cell property table.
 * Mode C (no cell, >1 selected): Multi-cell aggregate statistics.
 *
 * Panel state machine (driven by caller):
 *   0 selected cells → show hovered cell; mouse leave → planet summary
 *   1 selected cell  → show that cell (locked, survives mouse leave)
 *   >1 selected      → show aggregate stats
 */

import { useState, useMemo, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { VoronoiCell, CVTMesh } from '../../viewers/map/types'
import type { ColorMode } from '../../viewers/map/TerrainPlane'

interface MapCellInspectorProps {
  cell: VoronoiCell | null
  cvtMesh: CVTMesh | null
  /** Planet display name (for summary header). */
  planetName: string | null
  /** Multiple selected cells — triggers aggregate stats when cell===null. */
  selectedCells?: VoronoiCell[]
  /** Currently-active map layer — drives which inspector group auto-expands. */
  activeColorMode?: ColorMode | null
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const BOUNDARY_COLORS: Record<string, string> = {
  convergent: 'bg-red-900/40 text-red-300',
  divergent: 'bg-green-900/40 text-green-300',
  transform: 'bg-yellow-900/40 text-yellow-300',
}

const CRUST_LABELS: Record<string, string> = {
  continental: 'crust.continental',
  oceanic: 'crust.oceanic',
  transitional: 'crust.transitional',
}

const BOUNDARY_LABELS: Record<string, string> = {
  convergent: 'boundary.convergent',
  divergent: 'boundary.divergent',
  transform: 'boundary.transform',
}

/** Map layer → inspector field-group id (for the auto-expand linkage). */
const COLOR_MODE_TO_GROUP: Partial<Record<ColorMode, string>> = {
  terrain: 'position',
  landsea: 'position',
  plates: 'geology',
  boundaries: 'geology',
  koppen: 'climate',
  temperature: 'climate',
  precipitation: 'climate',
  pressure: 'climate',
  winds: 'climate',
  currents: 'climate',
  biomes: 'ecology',
  npp: 'ecology',
  domesticable: 'ecology',
  soil: 'ecology',
  provinces: 'ecology',
  habitable: 'civilization',
  agriculture: 'civilization',
}

const KOPPEN_NAMES: Record<string, string> = {
  Af: 'koppen.Af', Am: 'koppen.Am', Aw: 'koppen.Aw',
  BWh: 'koppen.BWh', BWk: 'koppen.BWk', BSh: 'koppen.BSh', BSk: 'koppen.BSk',
  Csa: 'koppen.Csa', Csb: 'koppen.Csb', Csc: 'koppen.Csc',
  Cwa: 'koppen.Cwa', Cwb: 'koppen.Cwb', Cwc: 'koppen.Cwc',
  Cfa: 'koppen.Cfa', Cfb: 'koppen.Cfb', Cfc: 'koppen.Cfc',
  Dsa: 'koppen.Dsa', Dsb: 'koppen.Dsb', Dsc: 'koppen.Dsc', Dsd: 'koppen.Dsd',
  Dwa: 'koppen.Dwa', Dwb: 'koppen.Dwb', Dwc: 'koppen.Dwc', Dwd: 'koppen.Dwd',
  Dfa: 'koppen.Dfa', Dfb: 'koppen.Dfb', Dfc: 'koppen.Dfc', Dfd: 'koppen.Dfd',
  ET: 'koppen.ET', EF: 'koppen.EF',
  Ocean: 'koppen.Ocean',
}

const BIOME_LABELS: Record<string, string> = {
  tropical_rainforest: 'biome.tropical_rainforest',
  tropical_seasonal_forest: 'biome.tropical_seasonal_forest',
  tropical_savanna: 'biome.tropical_savanna',
  tropical_desert: 'biome.tropical_desert',
  temperate_rainforest: 'biome.temperate_rainforest',
  temperate_forest: 'biome.temperate_forest',
  temperate_grassland: 'biome.temperate_grassland',
  temperate_desert: 'biome.temperate_desert',
  boreal_forest: 'biome.boreal_forest',
  boreal_shrubland: 'biome.boreal_shrubland',
  tundra: 'biome.tundra',
  ice: 'biome.ice',
  ocean: 'biome.ocean',
}

const TAG_LABELS: Record<string, string> = {
  large_herbivores_high: 'tag.large_herbivores_high',
  large_herbivores_moderate: 'tag.large_herbivores_moderate',
  large_herbivores_low: 'tag.large_herbivores_low',
  staple_crops_high: 'tag.staple_crops_high',
  staple_crops_moderate: 'tag.staple_crops_moderate',
  staple_crops_low: 'tag.staple_crops_low',
  draft_animals_high: 'tag.draft_animals_high',
  draft_animals_moderate: 'tag.draft_animals_moderate',
  draft_animals_low: 'tag.draft_animals_low',
}

const SOIL_LABELS: Record<string, string> = {
  gelisol: 'soil.gelisol',
  histosol: 'soil.histosol',
  spodosol: 'soil.spodosol',
  andisol: 'soil.andisol',
  oxisol: 'soil.oxisol',
  vertisol: 'soil.vertisol',
  aridisol: 'soil.aridisol',
  ultisol: 'soil.ultisol',
  mollisol: 'soil.mollisol',
  alfisol: 'soil.alfisol',
  inceptisol: 'soil.inceptisol',
  entisol: 'soil.entisol',
}

const FERTILITY_LABELS: Record<string, string> = {
  high: 'fertility.high',
  medium: 'fertility.medium',
  low: 'fertility.low',
}

const FERTILITY_COLORS: Record<string, string> = {
  high: 'text-green-400',
  medium: 'text-yellow-400',
  low: 'text-gray-400',
}

function formatNumber(n: number | undefined, decimals = 0): string {
  if (n === undefined || n === null) return '—'
  if (!isFinite(n)) return '∞'
  return n.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

// ---------------------------------------------------------------------------
// Mode A — Planet summary
// ---------------------------------------------------------------------------

function PlanetSummary({
  cvtMesh,
  planetName,
}: {
  cvtMesh: CVTMesh | null
  planetName: string | null
}) {
  const { t } = useTranslation('map')

  if (!cvtMesh) {
    return (
      <p className="text-xs text-gray-600 italic p-2">{t('inspector.loading')}</p>
    )
  }

  const cells = cvtMesh.cells
  const totalCells = cells.length

  // Aggregate stats over all cells
  let landCount = 0
  let landArea = 0
  let oceanArea = 0
  let continentalArea = 0
  let elevMin = Infinity
  let elevMax = -Infinity
  const plateIds = new Set<string>()

  for (const c of cells) {
    const area = c.area_km2 ?? 0
    const isLandCell = c.water_class != null ? c.water_class === 'land' : c.elevation > 0
    if (isLandCell) {
      landCount++
      landArea += area
    } else {
      oceanArea += area
    }
    if (c.crust_type === 'continental') continentalArea += area
    if (c.elevation < elevMin) elevMin = c.elevation
    if (c.elevation > elevMax) elevMax = c.elevation
    if (c.plate_id) plateIds.add(c.plate_id)
  }
  if (!isFinite(elevMin)) elevMin = 0
  if (!isFinite(elevMax)) elevMax = 0

  const totalCellsNum = totalCells
  const landPct = totalCellsNum > 0 ? ((landCount / totalCellsNum) * 100).toFixed(1) : '0'
  const seaPct = totalCellsNum > 0 ? (((totalCellsNum - landCount) / totalCellsNum) * 100).toFixed(1) : '0'
  const totalArea = landArea + oceanArea
  const crustPct = totalArea > 0 ? (continentalArea / totalArea * 100).toFixed(1) : '0'
  const seaLevel = 0
  const peakProminence = elevMax - seaLevel
  const maxOceanDepth = seaLevel - elevMin

  const fmtKm2 = (km2: number) =>
    km2 > 1_000_000
      ? `${(km2 / 1_000_000).toFixed(1)}M km²`
      : `${km2.toLocaleString(undefined, { maximumFractionDigits: 0 })} km²`

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-semibold text-neon-cyan">
          {planetName ?? t('inspector.unknownPlanet')}
        </h4>
        <p className="text-[10px] text-gray-600 font-mono">seed: {cvtMesh.seed}</p>
      </div>

      <dl className="space-y-1.5 text-xs">
        <div className="flex justify-between">
          <dt className="text-gray-500">{t('inspector.landSeaRatio')}</dt>
          <dd className="font-mono text-right">
            <span className="text-green-400">{landPct}%</span>
            <span className="text-gray-600"> / </span>
            <span className="text-blue-400">{seaPct}%</span>
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">{t('inspector.landArea')}</dt>
          <dd className="font-mono text-right text-green-400">{fmtKm2(landArea)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">{t('inspector.oceanArea')}</dt>
          <dd className="font-mono text-right text-blue-400">{fmtKm2(oceanArea)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">{t('inspector.totalArea')}</dt>
          <dd className="font-mono text-right">{fmtKm2(totalArea)}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">{t('inspector.crustRatio')}</dt>
          <dd className="font-mono text-right">
            {crustPct}% / {(100 - Number(crustPct)).toFixed(1)}%
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">{t('inspector.elevationRange')}</dt>
          <dd className="font-mono text-right">
            {formatNumber(Math.round(elevMin))} ~ {formatNumber(Math.round(elevMax))} m
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">{t('inspector.highestPoint')}</dt>
          <dd className="font-mono text-right">{formatNumber(Math.round(peakProminence))} m</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">{t('inspector.deepestSea')}</dt>
          <dd className="font-mono text-right">{formatNumber(Math.round(maxOceanDepth))} m</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">{t('inspector.plateCount')}</dt>
          <dd className="font-mono">{plateIds.size}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">{t('inspector.meshNodes')}</dt>
          <dd className="font-mono">{cvtMesh.vertices.length.toLocaleString()}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">{t('inspector.cellCount')}</dt>
          <dd className="font-mono">{totalCells.toLocaleString()}</dd>
        </div>
      </dl>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode B — Cell details
// ---------------------------------------------------------------------------

function Chevron({ open }: { open: boolean }) {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
         className={`transition-transform duration-150 ${open ? 'rotate-90' : ''}`}>
      <polyline points="9 6 15 12 9 18" />
    </svg>
  )
}

/** Collapsible field group (accordion). */
function FieldGroup({
  icon,
  label,
  defaultOpen = false,
  children,
}: {
  icon: string
  label: string
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 py-0.5 text-xs text-gray-300 hover:text-white select-none"
      >
        <Chevron open={open} />
        <span className="text-[13px] leading-none">{icon}</span>
        <span className="font-medium">{label}</span>
      </button>
      {open && <dl className="mt-1 ml-4 space-y-1 text-xs">{children}</dl>}
    </div>
  )
}

function CellDetails({
  cell,
  activeColorMode,
}: {
  cell: VoronoiCell
  activeColorMode?: ColorMode | null
}) {
  const { t } = useTranslation('map')
  const [displayMode, setDisplayMode] = useState<'default' | 'full'>('default')
  const highlightGroup = activeColorMode ? COLOR_MODE_TO_GROUP[activeColorMode] ?? null : null
  const elevM = cell.elevation
  const isLand = cell.water_class != null ? cell.water_class === 'land' : cell.elevation > 0
  const boundaryClass = cell.boundary_type
    ? BOUNDARY_COLORS[cell.boundary_type] ?? 'bg-gray-800 text-gray-300'
    : null
  const hasGeology = Boolean(
    cell.crust_type || cell.plate_id || cell.boundary_type || cell.hotspot_id || cell.landform,
  )
  const hasClimate = Boolean(
    cell.koppen_class || cell.temperature_C != null || cell.precipitation_mm != null ||
    (cell.wind_east_m_s != null && cell.wind_north_m_s != null) ||
    (cell.ocean_current_east_m_s != null && cell.ocean_current_north_m_s != null),
  )
  const hasEcology = Boolean(
    cell.biome || cell.npp_gc_m2_yr != null ||
    (cell.domesticable_tags && cell.domesticable_tags.length > 0) ||
    cell.soil_type || cell.soil_fertility || cell.biogeographic_province,
  )
  const hasCivilization = Boolean(
    cell.habitable_coast != null || cell.agricultural_core != null ||
    cell.habitability_score != null || cell.agriculture_score != null,
  )

  return (
    <div className="space-y-2 text-sm">
      <div className="flex items-center gap-2">
        <span className="text-neon-cyan font-semibold">Cell #{cell.id}</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded ${
            isLand ? 'bg-green-900/30 text-green-300' : 'bg-blue-900/30 text-blue-300'
          }`}
        >
          {isLand ? t('inspector.land') : t('inspector.ocean')}
        </span>
        <button
          type="button"
          onClick={() => setDisplayMode((m) => (m === 'default' ? 'full' : 'default'))}
          className="ml-auto text-[10px] text-gray-500 hover:text-gray-300"
          title={t('inspector.displayMode')}
        >
          {displayMode === 'default' ? t('inspector.displayModeDefault') : t('inspector.displayModeFull')}
        </button>
      </div>

      <div className="space-y-1">
        <FieldGroup icon="🧭" label={t('inspector.position')} defaultOpen>
          <div className="flex justify-between">
            <dt className="text-gray-500">{t('inspector.longitude')}</dt>
            <dd className="font-mono">{cell.lon.toFixed(2)}°</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">{t('inspector.latitude')}</dt>
            <dd className="font-mono">{cell.lat.toFixed(2)}°</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">{t('inspector.elevation')}</dt>
            <dd className={`font-mono ${elevM >= 0 ? 'text-green-400' : 'text-blue-400'}`}>
              {elevM >= 0 ? '+' : ''}
              {elevM.toFixed(1)} m
            </dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">{t('inspector.area')}</dt>
            <dd className="font-mono">
              {cell.area_km2 !== undefined
                ? `${formatNumber(Math.round(cell.area_km2))} km²`
                : '—'}
            </dd>
          </div>
        </FieldGroup>

        {hasGeology && (
          <FieldGroup
            icon="🪨"
            label={t('inspector.geology')}
            key={`geology-${displayMode}-${highlightGroup}`}
            defaultOpen={displayMode === 'full' || highlightGroup === 'geology'}
          >
            <div className="flex justify-between">
              <dt className="text-gray-500" title={t('tooltip.crustType')}>{t('inspector.crustType')}</dt>
              <dd className="font-mono">{t(CRUST_LABELS[cell.crust_type ?? ''] ?? cell.crust_type ?? '—')}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500" title={t('tooltip.plate')}>{t('inspector.plate')}</dt>
              <dd className="text-amber-300">
                {cell.plate_id ?? '—'}
              </dd>
            </div>
            <div className="flex justify-between items-center">
              <dt className="text-gray-500" title={t('tooltip.boundaryType')}>{t('inspector.boundaryType')}</dt>
              <dd>
                {cell.boundary_type ? (
                  <span className={`text-xs px-1.5 py-0.5 rounded ${boundaryClass}`}>
                    {t(BOUNDARY_LABELS[cell.boundary_type] ?? cell.boundary_type)}
                  </span>
                ) : (
                  <span className="text-gray-600">—</span>
                )}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500" title={t('tooltip.convergenceRate')}>{t('inspector.convergenceRate')}</dt>
              <dd className="font-mono">
                {cell.convergence_rate_cm_yr !== undefined
                  ? `${formatNumber(cell.convergence_rate_cm_yr, 1)} cm/yr`
                  : '—'}
              </dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-gray-500" title={t('tooltip.distanceToBoundary')}>{t('inspector.distanceToBoundary')}</dt>
              <dd className="font-mono">
                {cell.distance_to_boundary_km !== undefined
                  ? isFinite(cell.distance_to_boundary_km)
                    ? `${formatNumber(Math.round(cell.distance_to_boundary_km))} km`
                    : '∞'
                  : '—'}
              </dd>
            </div>
            {(cell.hotspot_id || cell.landform) && (
              <div className="flex justify-between">
                <dt className="text-gray-500" title={t('tooltip.specialCrust')}>{t('inspector.specialCrust')}</dt>
                <dd className={`font-mono text-xs ${
                  cell.hotspot_id ? 'text-fuchsia-400' :
                  cell.landform === 'orogeny' ? 'text-amber-400' :
                  'text-teal-400'
                }`}>
                  {cell.hotspot_id ? t('inspector.hotspotChain', { id: cell.hotspot_id }) :
                   cell.landform === 'orogeny' ? t('inspector.orogeny') :
                   cell.landform === 'rift' ? t('inspector.rift') : ''}
                </dd>
              </div>
            )}
          </FieldGroup>
        )}

        {hasClimate && (
          <FieldGroup
            icon="🌦️"
            label={t('inspector.climate')}
            key={`climate-${displayMode}-${highlightGroup}`}
            defaultOpen={displayMode === 'full' || highlightGroup === 'climate'}
          >
            {cell.koppen_class && (
              <div className="flex justify-between">
                <dt className="text-gray-500" title={t('tooltip.koppen')}>{t('inspector.koppenClimate')}</dt>
                <dd className="text-cyan-300">
                  {t(KOPPEN_NAMES[cell.koppen_class] ?? cell.koppen_class)}
                  <span className="text-gray-500 ml-1">({cell.koppen_class})</span>
                </dd>
              </div>
            )}
            {cell.temperature_C != null && (
              <div className="flex justify-between">
                <dt className="text-gray-500">{t('inspector.annualTemp')}</dt>
                <dd className="font-mono">{cell.temperature_C.toFixed(1)} °C</dd>
              </div>
            )}
            {(cell.temperature_hottest_month_C != null && cell.temperature_coldest_month_C != null) && (
              <div className="flex justify-between">
                <dt className="text-gray-500">{t('inspector.hottestColdest')}</dt>
                <dd className="font-mono">
                  {cell.temperature_hottest_month_C.toFixed(1)} / {cell.temperature_coldest_month_C.toFixed(1)} °C
                </dd>
              </div>
            )}
            {cell.precipitation_mm != null && (
              <div className="flex justify-between">
                <dt className="text-gray-500">{t('inspector.annualPrecip')}</dt>
                <dd className="font-mono">{Math.round(cell.precipitation_mm)} mm</dd>
              </div>
            )}
            {cell.distance_to_coast_km != null && (
              <div className="flex justify-between">
                <dt className="text-gray-500">{t('inspector.distanceToCoast')}</dt>
                <dd className="font-mono">{Math.round(cell.distance_to_coast_km)} km</dd>
              </div>
            )}
            {(cell.wind_east_m_s != null && cell.wind_north_m_s != null) && (
              <WindDetail u={cell.wind_east_m_s} v={cell.wind_north_m_s} />
            )}
            {(cell.ocean_current_east_m_s != null && cell.ocean_current_north_m_s != null) && (
              <OceanCurrentDetail u={cell.ocean_current_east_m_s} v={cell.ocean_current_north_m_s} sstAnom={cell.sst_anomaly_c ?? 0} />
            )}
          </FieldGroup>
        )}

        {hasEcology && (
          <FieldGroup
            icon="🌿"
            label={t('inspector.ecology')}
            key={`ecology-${displayMode}-${highlightGroup}`}
            defaultOpen={displayMode === 'full' || highlightGroup === 'ecology'}
          >
            {cell.biome && (
              <div className="flex justify-between">
                <dt className="text-gray-500">{t('inspector.whittakerBiome')}</dt>
                <dd className="text-green-300">{t(BIOME_LABELS[cell.biome] ?? cell.biome)}</dd>
              </div>
            )}
            {cell.npp_gc_m2_yr != null && (
              <div className="flex justify-between">
                <dt className="text-gray-500">{t('inspector.npp')}</dt>
                <dd className="font-mono">{cell.npp_gc_m2_yr.toFixed(0)} gC/m²/yr</dd>
              </div>
            )}
            {cell.domesticable_tags && cell.domesticable_tags.length > 0 && (
              <div className="flex justify-between">
                <dt className="text-gray-500">{t('inspector.domesticable')}</dt>
                <dd className="text-xs text-amber-300">
                  {cell.domesticable_tags
                    .filter((tag: string) => tag.endsWith('_high'))
                    .map((tag: string) => t(TAG_LABELS[tag] ?? tag))
                    .join(' · ') || '—'}
                </dd>
              </div>
            )}
            {cell.soil_type && (
              <div className="flex justify-between">
                <dt className="text-gray-500" title={t('tooltip.soilType')}>{t('inspector.soilType')}</dt>
                <dd className="text-amber-300">{t(SOIL_LABELS[cell.soil_type] ?? cell.soil_type)}</dd>
              </div>
            )}
            {cell.soil_fertility && (
              <div className="flex justify-between">
                <dt className="text-gray-500" title={t('tooltip.fertility')}>{t('inspector.soilFertility')}</dt>
                <dd className={`font-mono ${FERTILITY_COLORS[cell.soil_fertility] ?? ''}`}>
                  {t(FERTILITY_LABELS[cell.soil_fertility] ?? cell.soil_fertility)}
                </dd>
              </div>
            )}
            {cell.biogeographic_province && (
              <div className="flex justify-between">
                <dt className="text-gray-500" title={t('tooltip.province')}>{t('inspector.biogeographicProvince')}</dt>
                <dd className="font-mono">{cell.biogeographic_province}</dd>
              </div>
            )}
          </FieldGroup>
        )}

        {hasCivilization && (
          <FieldGroup
            icon="🏛️"
            label={t('inspector.civilization')}
            key={`civilization-${displayMode}-${highlightGroup}`}
            defaultOpen={displayMode === 'full' || highlightGroup === 'civilization'}
          >
            {cell.habitability_score != null && (
              <div className="flex justify-between">
                <dt className="text-gray-500">{t('inspector.habitableCoast')}</dt>
                <dd className="font-mono text-cyan-300">{cell.habitability_score.toFixed(1)}</dd>
              </div>
            )}
            {cell.agriculture_score != null && (
              <div className="flex justify-between">
                <dt className="text-gray-500">{t('inspector.agriculturalCore')}</dt>
                <dd className="font-mono text-green-400">{cell.agriculture_score.toFixed(1)}</dd>
              </div>
            )}
          </FieldGroup>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Wind detail (shown for all cells with wind data)
// ---------------------------------------------------------------------------

function WindDetail({ u, v }: { u: number; v: number }) {
  const { t } = useTranslation('map')
  const speed = Math.sqrt(u * u + v * v)
  const dirIdx = Math.round((Math.atan2(u, v) * 180 / Math.PI + 360) % 360 / 45) % 8
  return (
    <>
      <div className="flex justify-between">
        <dt className="text-gray-500">{t('inspector.windDirection')}</dt>
        <dd className="font-mono">{DIR_LABELS[dirIdx]} · {speed.toFixed(1)} m/s</dd>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Ocean current detail (inserted into CellDetails for ocean cells)
// ---------------------------------------------------------------------------

const DIR_LABELS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']

function OceanCurrentDetail({ u, v, sstAnom }: { u: number; v: number; sstAnom: number }) {
  const { t } = useTranslation('map')
  const speed = Math.sqrt(u * u + v * v) * 100  // m/s → cm/s
  const dirIdx = Math.round((Math.atan2(u, v) * 180 / Math.PI + 360) % 360 / 45) % 8
  const warm = sstAnom > 0
  const color = warm ? '#e040fb' : '#00bcd4'
  const label = warm ? t('inspector.warmCurrent') : t('inspector.coldCurrent')
  const uc = u * 100; const vc = v * 100
  return (
    <>
      <div className="flex justify-between">
        <dt className="text-gray-500">{t('inspector.currentDirection')}</dt>
        <dd className="font-mono" style={{ color }}>
          {DIR_LABELS[dirIdx]}（{label}）
        </dd>
      </div>
      <div className="flex justify-between">
        <dt className="text-gray-500">{t('inspector.speed')}</dt>
        <dd className="font-mono" style={{ color }}>
          {speed.toFixed(2)} cm/s
        </dd>
      </div>
      <div className="flex justify-between">
        <dt className="text-gray-500">{t('inspector.eastComponent')}</dt>
        <dd className="font-mono">{uc >= 0 ? '+' : ''}{uc.toFixed(1)}</dd>
      </div>
      <div className="flex justify-between">
        <dt className="text-gray-500">{t('inspector.northComponent')}</dt>
        <dd className="font-mono">{vc >= 0 ? '+' : ''}{vc.toFixed(1)}</dd>
      </div>
    </>
  )
}

// ---------------------------------------------------------------------------
// Mode C — Multi-cell statistics (>1 selected)
// ---------------------------------------------------------------------------

function MultiCellStats({ cells }: { cells: VoronoiCell[] }) {
  const { t } = useTranslation('map')
  const n = cells.length
  let totalArea = 0
  let landCount = 0
  let elevMin = Infinity
  let elevMax = -Infinity
  let elevSum = 0
  let tempSum = 0
  let tempCount = 0
  let precipSum = 0
  let precipCount = 0
  const koppenTally = new Map<string, number>()

  for (const c of cells) {
    const area = c.area_km2 ?? 0
    totalArea += area
    if (c.water_class != null ? c.water_class === 'land' : c.elevation > 0) landCount++
    if (c.elevation < elevMin) elevMin = c.elevation
    if (c.elevation > elevMax) elevMax = c.elevation
    elevSum += c.elevation
    if (c.temperature_C != null) { tempSum += c.temperature_C; tempCount++ }
    if (c.precipitation_mm != null) { precipSum += c.precipitation_mm; precipCount++ }
    if (c.koppen_class) {
      koppenTally.set(c.koppen_class, (koppenTally.get(c.koppen_class) ?? 0) + 1)
    }
  }

  // Dominant Köppen
  let dominantKoppen = ''
  let dominantCount = 0
  for (const [k, v] of koppenTally) {
    if (v > dominantCount) { dominantKoppen = k; dominantCount = v }
  }

  const elevAvg = elevSum / n
  const landPct = ((landCount / n) * 100).toFixed(0)

  const fmtArea = (km2: number) =>
    km2 > 1_000_000
      ? `${(km2 / 1_000_000).toFixed(1)}M km²`
      : `${Math.round(km2).toLocaleString()} km²`

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-semibold text-amber-300">
          {t('inspector.selectedCells', { n })}
        </h4>
        <p className="text-[10px] text-gray-600 font-mono">
          {t('inspector.landOfArea', { pct: landPct, area: fmtArea(totalArea) })}
        </p>
      </div>

      <dl className="space-y-1.5 text-xs">
        <div className="flex justify-between">
          <dt className="text-gray-500">{t('inspector.elevationRange')}</dt>
          <dd className="font-mono text-right">
            {isFinite(elevMin) ? `${Math.round(elevMin)}` : '—'}
            {' ~ '}
            {isFinite(elevMax) ? `${Math.round(elevMax)}` : '—'} m
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-gray-500">{t('inspector.avgElevation')}</dt>
          <dd className="font-mono text-right">
            {isFinite(elevAvg) ? `${Math.round(elevAvg)} m` : '—'}
          </dd>
        </div>

        <div className="border-t border-space-border pt-1 mt-1" />

        {tempCount > 0 && (
          <div className="flex justify-between">
            <dt className="text-gray-500">{t('inspector.avgTemp')}</dt>
            <dd className="font-mono text-right">{(tempSum / tempCount).toFixed(1)} °C</dd>
          </div>
        )}
        {precipCount > 0 && (
          <div className="flex justify-between">
            <dt className="text-gray-500">{t('inspector.avgPrecip')}</dt>
            <dd className="font-mono text-right">{Math.round(precipSum / precipCount)} mm</dd>
          </div>
        )}

        {dominantKoppen && (
          <>
            <div className="border-t border-space-border pt-1 mt-1" />
            <div className="flex justify-between">
              <dt className="text-gray-500">{t('inspector.dominantClimate')}</dt>
              <dd className="text-cyan-300">
                {t(KOPPEN_NAMES[dominantKoppen] ?? dominantKoppen)}
                <span className="text-gray-500 ml-1">({dominantKoppen})</span>
              </dd>
            </div>
            <p className="text-[10px] text-gray-600">
              {t('inspector.cellOfN', { count: dominantCount, n, pct: (dominantCount / n * 100).toFixed(0) })}
            </p>
          </>
        )}
      </dl>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mode D — World statistics (stats tab)
// ---------------------------------------------------------------------------

/** Top-N entries of a tally, descending by count. */
function topN<K>(map: Map<K, number>, n: number): [K, number][] {
  return [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, n)
}

interface WorldStatsData {
  tempMean: number
  tempMin: number
  tempMax: number
  precipMean: number
  nppMean: number
  koppen: Map<string, number>
  biome: Map<string, number>
  soil: Map<string, number>
  provinceCount: number
}

/** One pass over all cells → climate & ecology tallies for the stats tab. */
function computeWorldStats(cvtMesh: CVTMesh): WorldStatsData {
  const cells = cvtMesh.cells
  let tSum = 0, tCount = 0, tMin = Infinity, tMax = -Infinity
  let pSum = 0, pCount = 0
  let nSum = 0, nCount = 0
  const koppen = new Map<string, number>()
  const biome = new Map<string, number>()
  const soil = new Map<string, number>()
  const provinces = new Set<string>()

  for (const c of cells) {
    if (c.temperature_C != null) {
      tSum += c.temperature_C; tCount++
      if (c.temperature_C < tMin) tMin = c.temperature_C
      if (c.temperature_C > tMax) tMax = c.temperature_C
    }
    if (c.precipitation_mm != null) { pSum += c.precipitation_mm; pCount++ }
    if (c.npp_gc_m2_yr != null) { nSum += c.npp_gc_m2_yr; nCount++ }
    if (c.koppen_class && c.koppen_class !== 'Ocean') koppen.set(c.koppen_class, (koppen.get(c.koppen_class) ?? 0) + 1)
    if (c.biome && c.biome !== 'ocean') biome.set(c.biome, (biome.get(c.biome) ?? 0) + 1)
    if (c.soil_type) soil.set(c.soil_type, (soil.get(c.soil_type) ?? 0) + 1)
    if (c.biogeographic_province) provinces.add(c.biogeographic_province)
  }

  return {
    tempMean: tCount ? tSum / tCount : 0,
    tempMin: isFinite(tMin) ? tMin : 0,
    tempMax: isFinite(tMax) ? tMax : 0,
    precipMean: pCount ? pSum / pCount : 0,
    nppMean: nCount ? nSum / nCount : 0,
    koppen, biome, soil, provinceCount: provinces.size,
  }
}

function WorldStats({ cvtMesh, planetName }: { cvtMesh: CVTMesh | null; planetName: string | null }) {
  const { t } = useTranslation('map')
  const stats = useMemo(() => (cvtMesh ? computeWorldStats(cvtMesh) : null), [cvtMesh])
  if (!cvtMesh || !stats) {
    return <p className="text-xs text-gray-600 italic p-2">{t('inspector.loading')}</p>
  }

  const landCells = [...stats.biome.values()].reduce((a, b) => a + b, 0)

  return (
    <div className="space-y-3">
      <PlanetSummary cvtMesh={cvtMesh} planetName={planetName} />

      <section>
        <h4 className="text-xs font-semibold text-gray-400 mb-1.5">🌦️ {t('inspector.climate')}</h4>
        <dl className="space-y-1 text-xs">
          <div className="flex justify-between">
            <dt className="text-gray-500">{t('inspector.globalTemp')}</dt>
            <dd className="font-mono">{stats.tempMean.toFixed(1)} °C</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">{t('inspector.tempRange')}</dt>
            <dd className="font-mono">{stats.tempMin.toFixed(0)} ~ {stats.tempMax.toFixed(0)} °C</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">{t('inspector.globalPrecip')}</dt>
            <dd className="font-mono">{Math.round(stats.precipMean)} mm/yr</dd>
          </div>
          <div className="border-t border-space-border pt-1 mt-1" />
          <p className="text-[10px] text-gray-600">{t('inspector.koppenShare')}</p>
          {topN(stats.koppen, 5).map(([k, count]) => (
            <div key={k} className="flex justify-between">
              <dt className="text-gray-500">{t(KOPPEN_NAMES[k] ?? k)}</dt>
              <dd className="font-mono text-cyan-300">{(count / landCells * 100).toFixed(1)}%</dd>
            </div>
          ))}
        </dl>
      </section>

      <section>
        <h4 className="text-xs font-semibold text-gray-400 mb-1.5">🌿 {t('inspector.ecology')}</h4>
        <dl className="space-y-1 text-xs">
          <div className="flex justify-between">
            <dt className="text-gray-500">{t('inspector.avgNpp')}</dt>
            <dd className="font-mono">{stats.nppMean.toFixed(0)} gC/m²/yr</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-500">{t('inspector.provinceCount')}</dt>
            <dd className="font-mono">{stats.provinceCount}</dd>
          </div>
          <div className="border-t border-space-border pt-1 mt-1" />
          <p className="text-[10px] text-gray-600">{t('inspector.biomeShare')}</p>
          {topN(stats.biome, 5).map(([b, count]) => (
            <div key={b} className="flex justify-between">
              <dt className="text-gray-500">{t(BIOME_LABELS[b] ?? b)}</dt>
              <dd className="font-mono text-green-300">{(count / landCells * 100).toFixed(1)}%</dd>
            </div>
          ))}
          <div className="border-t border-space-border pt-1 mt-1" />
          <p className="text-[10px] text-gray-600">{t('inspector.soilShare')}</p>
          {topN(stats.soil, 5).map(([s, count]) => (
            <div key={s} className="flex justify-between">
              <dt className="text-gray-500">{t(SOIL_LABELS[s] ?? s)}</dt>
              <dd className="font-mono text-amber-300">{(count / landCells * 100).toFixed(1)}%</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MapCellInspector({
  cell,
  cvtMesh,
  planetName,
  selectedCells,
  activeColorMode,
}: MapCellInspectorProps) {
  const { t } = useTranslation('map')
  const [view, setView] = useState<'cell' | 'stats'>('cell')

  return (
    <div className="space-y-2">
      {/* View toggle: cell details / world stats */}
      <div className="flex rounded-md bg-gray-800/60 p-0.5">
        <button
          type="button"
          onClick={() => setView('cell')}
          className={`flex-1 text-xs py-1 rounded transition-colors ${
            view === 'cell' ? 'bg-neon-cyan/20 text-neon-cyan' : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          {t('inspector.cellTab')}
        </button>
        <button
          type="button"
          onClick={() => setView('stats')}
          className={`flex-1 text-xs py-1 rounded transition-colors ${
            view === 'stats' ? 'bg-neon-cyan/20 text-neon-cyan' : 'text-gray-500 hover:text-gray-300'
          }`}
        >
          {t('inspector.statsTab')}
        </button>
      </div>

      {view === 'stats' ? (
        <WorldStats cvtMesh={cvtMesh} planetName={planetName} />
      ) : !cell && selectedCells && selectedCells.length > 1 ? (
        <MultiCellStats cells={selectedCells} />
      ) : cell ? (
        <CellDetails cell={cell} activeColorMode={activeColorMode} />
      ) : (
        <p className="text-xs text-gray-600 italic p-2">{t('inspector.hoverHint')}</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mobile cell card — compact single-cell summary for the phone layout
// (the full right-panel inspector is hidden below the md breakpoint).
// ---------------------------------------------------------------------------

export function MobileCellCard({
  cell,
  cursor,
  onClose,
}: {
  cell: VoronoiCell | null
  cursor: { lon: number; lat: number } | null
  onClose: () => void
}) {
  const { t } = useTranslation('map')
  const elevM = cell ? cell.elevation : 0
  const isLand = cell
    ? cell.water_class != null
      ? cell.water_class === 'land'
      : cell.elevation > 0
    : false

  return (
    <div className="bg-space-panel/95 border-t border-space-border px-3 py-2 text-xs">
      <div className="flex items-center gap-2 mb-1">
        {cell ? (
          <>
            <span className="text-neon-cyan font-semibold">Cell #{cell.id}</span>
            <span className={`px-1.5 py-0.5 rounded ${isLand ? 'bg-green-900/30 text-green-300' : 'bg-blue-900/30 text-blue-300'}`}>
              {isLand ? t('inspector.land') : t('inspector.ocean')}
            </span>
          </>
        ) : (
          <span className="text-gray-500">{t('inspector.clickHint')}</span>
        )}
        {cursor && (
          <span className="ml-auto font-mono text-gray-500 tabular-nums">
            {cursor.lon.toFixed(1)}°, {cursor.lat.toFixed(1)}°
          </span>
        )}
        {cell && (
          <button
            onClick={onClose}
            className="px-1 text-gray-500 hover:text-gray-300 text-sm leading-none"
            aria-label={t('inspector.close')}
          >
            ✕
          </button>
        )}
      </div>

      {cell && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-gray-300">
          <span className={elevM >= 0 ? 'text-green-400' : 'text-blue-400'}>
            {t('inspector.elevation')} {elevM >= 0 ? '+' : ''}{elevM.toFixed(1)}m
          </span>
          {cell.koppen_class && (
            <span className="text-cyan-300">{t(KOPPEN_NAMES[cell.koppen_class] ?? cell.koppen_class)}</span>
          )}
          {cell.temperature_C != null && <span>{cell.temperature_C.toFixed(1)}°C</span>}
          {cell.precipitation_mm != null && <span>{Math.round(cell.precipitation_mm)}mm</span>}
        </div>
      )}

      {cell && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-gray-400">
          {cell.biome && <span className="text-green-300">{t(BIOME_LABELS[cell.biome] ?? cell.biome)}</span>}
          {cell.soil_type && <span className="text-amber-300">{t(SOIL_LABELS[cell.soil_type] ?? cell.soil_type)}</span>}
          {cell.npp_gc_m2_yr != null && <span className="font-mono">{t('inspector.npp')} {cell.npp_gc_m2_yr.toFixed(0)}</span>}
          {cell.biogeographic_province && <span className="font-mono">{t('inspector.province', { name: cell.biogeographic_province })}</span>}
        </div>
      )}
    </div>
  )
}
