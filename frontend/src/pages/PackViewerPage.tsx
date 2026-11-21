/**
 * A global selection opens the browser's regional extract view. Local packs
 * also expose the recorded conditioning and hydrology used in refinement.
 */

import { useMemo, useState, type ReactNode } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api, ApiError, packTopoUrl } from '../api/client'
import { isStaticMode } from '../api/mode'
import MapHelpLink from '../components/map/MapHelpLink'
import { REGION_WINDOW_PARAM, readRegionWindow } from '../viewers/map/regionWindow'
import type { LonLat } from '../viewers/map/utils/mapCoords'
import PackMap from '../viewers/packs/PackMap'
import PackStatusBar from '../viewers/packs/PackStatusBar'
import ProbePanel, { type RegionInspectorFields } from '../viewers/packs/ProbePanel'
import RegionalExtractView from '../viewers/packs/RegionalExtractView'
import RegionResultSelector from '../viewers/packs/RegionResultSelector'
import RegionMapWorkspace from '../viewers/packs/RegionMapWorkspace'
import RegionLayerPanel from '../viewers/packs/RegionLayerPanel'
import SavedRegionView from '../viewers/packs/SavedRegionView'
import PackElevationDownload from '../viewers/packs/PackElevationDownload'
import RegionRefinementPanel from '../viewers/packs/RegionRefinementPanel'
import TerrainCompute from '../viewers/packs/TerrainCompute'
import type { PackHeightSource, PackInputMeta, PackMeta } from '../viewers/packs/types'
import { lonLatToKm, type PackWindow } from '../viewers/packs/packCoords'
import { indexRegionRivers, regionConditionSources, regionFieldLayers, regionFieldSource, regionFields, regionPackBaseLayers,
  type RegionPackBaseLayer, type RegionRasterSource } from '../viewers/packs/regionPackLayers'
import { readElevationNpy } from '../viewers/packs/elevationRaster'
import { useElevationPreview } from '../viewers/packs/useElevationPreview'
import { useRegionContext } from '../viewers/packs/useRegionContext'
import { useRegionFieldPreview } from '../viewers/packs/useRegionFieldPreview'
import { useRegionElevation, type ElevationInput } from '../viewers/packs/useRegionElevation'

function windowOf(meta: PackMeta): PackWindow {
  const i = meta.input
  return {
    centerLat: i.center_lat,
    centerLon: i.center_lon,
    radiusKm: i.radius_km ?? 6371,
    extentKmX: i.extent_km.x,
    extentKmY: i.extent_km.y,
    projection: i.projection === 'azimuthal_equidistant' ? i.projection : undefined,
  }
}

function packPalette(input: PackInputMeta | undefined) {
  const range = input?.elevation_m_global ?? input?.height_png_range_m
  const sea = input?.sea_level_m
  if (!Array.isArray(range) || !range.every(value => typeof value === 'number' && Number.isFinite(value)) ||
    range.length !== 2 || typeof sea !== 'number' || !Number.isFinite(sea)) return null
  const [min, max] = range as [number, number]
  return { min: !input?.elevation_m_global && min > sea ? sea - 1000 : min, max, sea }
}

function usePackHeight(pack: string | null, source: PackHeightSource | null | undefined, enabled: boolean) {
  const numeric = useQuery({ queryKey: ['packElevation', pack, source], enabled: Boolean(pack && source && enabled), retry: false,
    queryFn: () => api.getPackElevation(pack!, source!) })
  const input = useMemo<ElevationInput | null>(() => numeric.data ? { kind: 'pack', blob: numeric.data, previewSide: 2048 } : null,
    [numeric.data])
  const height = useRegionElevation(input)
  return { raster: height.ready?.kind === 'preview' ? height.ready.raster : undefined, failed: height.failed || numeric.isError }
}

export default function PackViewerPage() {
  const { t } = useTranslation('map')
  const [search] = useSearchParams()
  const { state } = useLocation()
  const project = search.get('project')
  const layer = search.get('layer')
  const branch = search.get('branch') || null
  if (project !== null) {
    return <SavedRegionView key={search.toString()} projectId={project} layerId={layer} branch={branch} />
  }
  const world = search.get('world')
  const planet = search.get('planet')
  const radiusKm = Number(search.get('radius'))
  const rawWindow = search.get(REGION_WINDOW_PARAM)
  const selection = readRegionWindow(rawWindow, radiusKm)
  if (world && planet && selection) {
    const globalParams = new URLSearchParams({ [REGION_WINDOW_PARAM]: rawWindow! })
    if (branch) globalParams.set('branch', branch)
    const view = search.get('view') === 'globe' ? 'globe' : 'map'
    const globalReturn = typeof state?.regionReturn === 'string' ? state.regionReturn
      : `/worlds/${encodeURIComponent(world)}/${view}/${encodeURIComponent(planet)}?${globalParams}`
    const sourceControl = !isStaticMode() && <RegionResultSelector world={world} planet={planet} branch={branch}
      radiusKm={radiusKm} selection={selection} globalReturn={globalReturn} />
    if (!search.has('pack') || isStaticMode()) {
      return <RegionalExtractView key={search.toString()} world={world} planet={planet} branch={branch}
        radiusKm={radiusKm} selection={selection} globalReturn={globalReturn} regionParams={search} sourceControl={sourceControl} />
    }
    return <ExistingPackViewer key={search.get('pack')} globalReturn={globalReturn} sourceControl={sourceControl} />
  }
  if (rawWindow !== null) {
    return <div className="space-y-3 p-4">
      <h1 className="font-semibold text-gray-200">{t('packs.pickPrompt')}</h1>
      <p role="alert" className="text-sm text-gray-300">{t('packs.export.invalidSelection')}</p>
      <Link to="/worlds" className="inline-flex min-h-11 items-center text-sm text-neon-cyan hover:underline">{t('packs.entry.openWorlds')}</Link>
    </div>
  }
  return <ExistingPackViewer key={search.get('pack')} />
}

function ExistingPackViewer({ globalReturn, sourceControl }: { globalReturn?: string; sourceControl?: ReactNode }) {
  const { t } = useTranslation('map')
  const staticMode = isStaticMode()
  const { state } = useLocation()
  const regionReturn = globalReturn ?? (typeof state?.regionReturn === 'string' ? state.regionReturn : null)

  const [searchParams, setSearchParams] = useSearchParams()
  const pack = searchParams.get('pack') || null
  const packs = useQuery({ queryKey: ['packs'], queryFn: api.listPacks, enabled: !staticMode, retry: false, staleTime: 0 })
  const metaQuery = useQuery({ queryKey: ['packMeta', pack], queryFn: () => api.getPackMeta(pack!),
    enabled: !staticMode && !!pack, retry: false, staleTime: 0 })
  const rivers = useQuery({ queryKey: ['packRivers', pack], queryFn: () => api.getPackRivers(pack!),
    enabled: !staticMode && !!pack && metaQuery.isSuccess, retry: false, staleTime: 0 })
  const meta = metaQuery.data ?? null
  const summary = packs.data?.find((item) => item.name === pack) ?? null
  const [requestedBase, setRequestedBase] = useState<RegionPackBaseLayer>('mapElevation')
  const [requestedSource, setRequestedSource] = useState<RegionRasterSource>('grid')
  const [showOriginal, setShowOriginal] = useState(false)
  const [graticule, setGraticule] = useState(1)
  const [riverOpacity, setRiverOpacity] = useState(1)
  const [hover, setHover] = useState<LonLat | null>(null)
  const [pin, setPin] = useState<LonLat | null>(null)
  const point = pin ?? hover

  const selectPack = (name: string | null) => {
    const next = new URLSearchParams(searchParams)
    if (name) next.set('pack', name)
    else next.delete('pack')
    setSearchParams(next, { replace: true, state })
  }

  const win = useMemo(() => (meta ? windowOf(meta) : null), [meta])
  const choices = regionConditionSources(meta)
  const source = choices.includes(requestedSource) ? requestedSource : choices[0] ?? requestedSource
  const availableBase = new Set<RegionPackBaseLayer>(regionPackBaseLayers.filter(layer => layer === 'mapElevation'
    ? Boolean(meta?.height_source) : Boolean(regionFieldSource(meta, layer, source))))
  const baseId = availableBase.has(requestedBase) ? requestedBase : regionPackBaseLayers.find(id => availableBase.has(id)) ?? 'mapElevation'
  const canCompare = meta?.height_source === 'refined-out'
  const refinementPack = pack && !pack.startsWith('web-region-') ? pack : null
  const original = canCompare && showOriginal && baseId === 'mapElevation'
  const heightSource = meta?.height_source
  const palette = useMemo(() => packPalette(meta?.input), [meta])
  const worldLocation = summary?.world && summary.planet ? { world: summary.world, planet: summary.planet, branch: summary.branch } : null
  const context = useRegionContext(worldLocation, win, palette)
  const sources = regionFieldLayers.map(layer => regionFieldSource(meta, layer, source))
  const conditions = useQueries({ queries: regionFieldLayers.map((layer, index) => {
    const field = regionFields[layer].field
    const fieldSource = sources[index]
    return { queryKey: ['packCondition', pack, fieldSource, field], enabled: Boolean(pack && fieldSource),
      retry: false, queryFn: async () => readElevationNpy(await (await api.getPackCondition(pack!, fieldSource!, field)).arrayBuffer()) }
  }) })
  const fields: RegionInspectorFields = {}
  regionFieldLayers.forEach((layer, index) => {
    const fieldSource = sources[index]
    const query = conditions[index]
    if (fieldSource) fields[layer] = { source: fieldSource, raster: query.data, loading: query.isPending, failed: query.isError }
  })
  const conditionLayer = baseId === 'mapElevation' ? undefined : baseId
  const condition = conditionLayer ? fields[conditionLayer] : undefined
  const conditionPreview = useRegionFieldPreview(condition?.raster, conditionLayer)
  const terrainHeight = usePackHeight(pack, heightSource, Boolean(palette))
  const originalHeight = usePackHeight(pack, canCompare ? 'input' : null, Boolean(palette && (original || point)))
  const displayedHeight = original ? originalHeight : terrainHeight
  const terrain = useElevationPreview(baseId === 'mapElevation' ? displayedHeight.raster ?? null : null,
    palette?.min ?? 0, palette?.max ?? 0, palette?.sea ?? 0, true)
  const probe = useQuery({ queryKey: ['packProbe', pack, pin], enabled: Boolean(pack && pin), retry: false,
    queryFn: () => api.probePack(pack!, pin!.lat, pin!.lon) })
  const riverIndex = useMemo(() => rivers.data && indexRegionRivers(rivers.data), [rivers.data])
  const river = pin && probe.data?.river_flow_accum != null
    ? { flow: probe.data.river_flow_accum, regime: probe.data.river_regime ?? undefined }
    : point && win ? riverIndex?.(lonLatToKm(point, win)) : undefined

  const base = useMemo(() => {
    if (!pack) return null
    if (conditionLayer) return conditionPreview
    if (!heightSource) return null
    return !palette || displayedHeight.failed ? { url: packTopoUrl(pack, original) } : terrain
  }, [conditionLayer, pack, heightSource, original, palette, displayedHeight.failed, terrain, conditionPreview])

  if (staticMode) {
    return (
      <div className="flex justify-center p-4 md:pt-24">
        <div className="h-fit max-w-md space-y-3 rounded-lg border border-space-border bg-space-panel p-6 text-sm text-gray-400">
          <div className="flex items-center justify-between gap-3 mb-2">
            <h1 className="font-semibold text-gray-200">{t('packs.pickPrompt')}</h1>
            <MapHelpLink section="packs" label={t('packs.help')} />
          </div>
          <p>{t('packs.staticModeHint')}</p>
          <Link to="/worlds" className="inline-flex min-h-11 items-center text-neon-cyan hover:underline">{t('packs.entry.openWorlds')}</Link>
          <TerrainCompute />
        </div>
      </div>
    )
  }

  const missingPack = metaQuery.error instanceof ApiError && metaQuery.error.status === 404
  const hasEntryError = pack ? metaQuery.isError : packs.isError
  const entryMessage = pack
    ? missingPack ? 'packs.entry.notFound' : metaQuery.isError ? 'packs.noMeta' : 'status.loading'
    : packs.isPending ? 'packs.entry.loadingList' : packs.isError ? 'packs.entry.listFailed'
      : packs.data?.length ? 'packs.entry.chooseHint' : 'packs.noPacks'
  const openWorlds = (!pack || missingPack) && packs.isSuccess && !packs.data.length
  const retry = pack && !missingPack && metaQuery.isError ? metaQuery.refetch
    : !pack && packs.isError ? packs.refetch : null

  const packChooser = <>
          <select
            value={pack ?? ''}
            aria-label={t('packs.entry.choose')}
            title={t('packs.hint.pick')}
            onChange={(event) => selectPack(event.target.value || null)}
            disabled={!packs.data?.length}
            className="min-h-11 w-full min-w-0 rounded border border-space-border bg-space-surface px-2 text-sm text-gray-200 disabled:text-gray-400 lg:min-h-8 lg:text-xs"
          >
            <option value="">{t('packs.entry.choose')}</option>
            {pack && !summary && <option value={pack}>{pack}</option>}
            {packs.data?.map((item) => (
              <option key={item.name} value={item.name}>
                {item.world ?? item.name} · {item.center_lat}°, {item.center_lon}° · {Math.round(item.span_km)} km
              </option>
            ))}
          </select>
          {pack && packs.isError && <button type="button" onClick={() => void packs.refetch()}
            className="min-h-9 text-xs text-neon-cyan hover:underline">{t('packs.entry.retryList')}</button>}
  </>

  return (
    <RegionMapWorkspace backTo={regionReturn ?? '/worlds'} backLabel={t(regionReturn ? 'regionWindow.back' : 'packs.entry.openWorlds')}
      subtitle={win ? t('regionWindow.summary', { lat: win.centerLat, lon: win.centerLon, spanKm: summary?.span_km ?? win.extentKmX }) : undefined}
      sourceControl={sourceControl}
      tools={win && !sourceControl ? packChooser : undefined}
      status={win && <PackStatusBar hover={hover} window={win} />}
      inspector={win && <ProbePanel point={point} window={win} active={baseId} source={source} fields={fields} probe={probe.data}
        showingOriginal={original} river={river} original={heightSource === 'input' ? terrainHeight.raster : originalHeight.raster}
        refined={heightSource !== 'input' ? terrainHeight.raster : undefined} />}
      onClearPoint={pin ? () => setPin(null) : undefined}
      layers={win && <RegionLayerPanel availableBase={availableBase}
        value={baseId} onSelect={setRequestedBase} compare={canCompare ? { original: showOriginal, onChange: setShowOriginal } : undefined}
        notice={meta?.refined?.td_revision && !meta?.condition_layers?.grid.length ? 'missingGrid' : undefined}
        conditions={choices.length ? { source, choices, onChange: setRequestedSource } : undefined}
        rasterSize={condition?.raster && `${condition.raster.width} × ${condition.raster.height}`}
        graticule={{ opacity: graticule, onChange: setGraticule }}
        rivers={rivers.data?.segs.length ? { opacity: riverOpacity, disabled: original, onChange: setRiverOpacity } : undefined} />}
      canRefine={Boolean(refinementPack)} regionTools={win && <>
            {summary && <p className="break-words text-xs text-gray-400" title={t('packs.hint.source')}>
              {summary.branch ? `${summary.branch} · ` : ''}{summary.mtime}
            </p>}
            {pack && meta?.height_source && <PackElevationDownload key={`${pack}:${original ? 'input' : meta.height_source}`}
              pack={pack} source={original ? 'input' : meta.height_source} input={meta.input} summary={summary} />}
            {meta?.height_source === null && <p className="text-xs text-gray-400">{t('packs.export.noNumeric')}</p>}
            {refinementPack && <TerrainCompute><RegionRefinementPanel source={{ kind: 'pack', pack: refinementPack }} globalReturn={regionReturn}
              resultUrl={(result) => {
                const params = new URLSearchParams(searchParams)
                params.set('pack', result)
                return `/packs?${params}`
              }} /></TerrainCompute>}
      </>}>
      {win ? <><PackMap window={win} base={base} loading={!base && (conditionLayer ? Boolean(condition && !condition.failed) : Boolean(heightSource))} context={context}
        rivers={original || !riverOpacity ? null : rivers.data ?? null} riverOpacity={riverOpacity}
        graticuleOpacity={graticule} pin={pin} onHover={setHover} onLockPoint={setPin} />
        {condition?.failed && <p role="alert" className="absolute left-3 top-3 z-[500] rounded border border-space-border bg-space-bg px-2 py-1 text-xs text-red-300">
          {t('packs.conditions.unavailable')}</p>}</> : (
        <div className="max-w-lg space-y-2 px-3 py-5 text-sm text-gray-300 sm:px-4">
          {!sourceControl && packChooser}
          <p role={hasEntryError ? 'alert' : 'status'}>{t(entryMessage)}</p>
          {retry && <button type="button" onClick={() => void retry()} className="min-h-11 text-neon-cyan hover:underline">
            {t('packs.export.retry')}
          </button>}
          {openWorlds && <Link to="/worlds" className="inline-flex min-h-11 items-center text-neon-cyan hover:underline">
            {t('packs.entry.openWorlds')}
          </Link>}
        </div>
      )}
    </RegionMapWorkspace>
  )
}
