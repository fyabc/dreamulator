/**
 * A global selection opens the browser's regional extract view. Local packs
 * also expose the recorded conditioning and hydrology used in refinement.
 */

import { useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api, ApiError, packTopoUrl } from '../api/client'
import { isStaticMode } from '../api/mode'
import MapHelpLink from '../components/map/MapHelpLink'
import { REGION_WINDOW_PARAM, readRegionWindow } from '../viewers/map/regionWindow'
import type { LonLat } from '../viewers/map/utils/mapCoords'
import PackMap from '../viewers/packs/PackMap'
import PackStatusBar from '../viewers/packs/PackStatusBar'
import ProbePanel from '../viewers/packs/ProbePanel'
import RegionalExtractView from '../viewers/packs/RegionalExtractView'
import RegionResultSelector from '../viewers/packs/RegionResultSelector'
import RegionMapWorkspace from '../viewers/packs/RegionMapWorkspace'
import RegionLayerPanel from '../viewers/packs/RegionLayerPanel'
import SavedRegionView from '../viewers/packs/SavedRegionView'
import PackElevationDownload from '../viewers/packs/PackElevationDownload'
import RegionRefinementPanel from '../viewers/packs/RegionRefinementPanel'
import TerrainCompute from '../viewers/packs/TerrainCompute'
import type { PackInputMeta, PackMeta, ProbeResult } from '../viewers/packs/types'
import type { PackWindow } from '../viewers/packs/packCoords'
import { regionFields, regionPackBaseLayers, regionRasterSource, regionRasterSources,
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
  const [requestedBase, setRequestedBase] = useState<RegionPackBaseLayer>('terrain')
  const [requestedSources, setRequestedSources] = useState<Partial<Record<RegionPackBaseLayer, RegionRasterSource>>>({})
  const [showOriginal, setShowOriginal] = useState(false)
  const [graticule, setGraticule] = useState(1)
  const [riverOpacity, setRiverOpacity] = useState(1)
  const [hover, setHover] = useState<LonLat | null>(null)
  const [pin, setPin] = useState<LonLat | null>(null)
  const [probe, setProbe] = useState<ProbeResult | null>(null)
  const [probeLoading, setProbeLoading] = useState(false)
  const [probeError, setProbeError] = useState<string | null>(null)
  const probeSeq = useRef(0)

  const selectPack = (name: string | null) => {
    const next = new URLSearchParams(searchParams)
    if (name) next.set('pack', name)
    else next.delete('pack')
    setSearchParams(next, { replace: true, state })
  }

  const win = useMemo(() => (meta ? windowOf(meta) : null), [meta])
  const availableBase = useMemo(() => new Set(regionPackBaseLayers.filter(id => regionRasterSources(meta, id).length)), [meta])
  const baseId = availableBase.has(requestedBase) ? requestedBase : regionPackBaseLayers.find(id => availableBase.has(id)) ?? 'terrain'
  const choices = regionRasterSources(meta, baseId)
  const temperatureSources = regionRasterSources(meta, 'temperature')
  const representation = regionRasterSource(choices, requestedSources[baseId])
  const canCompare = meta?.height_source === 'refined-out' && representation === 'map'
  const original = canCompare && showOriginal

  const heightSource = original ? 'input' : meta?.height_source
  const palette = useMemo(() => packPalette(meta?.input), [meta])
  const worldLocation = summary?.world && summary.planet ? { world: summary.world, planet: summary.planet, branch: summary.branch } : null
  const context = useRegionContext(worldLocation, win, palette)
  const fieldSource = representation === 'source' || representation === 'grid' ? representation : undefined
  const field = regionFields[baseId].field
  const condition = useQuery({ queryKey: ['packCondition', pack, fieldSource, field], enabled: Boolean(pack && fieldSource),
    retry: false, queryFn: async () => readElevationNpy(await (await api.getPackCondition(pack!, fieldSource!, field)).arrayBuffer()) })
  const conditionPreview = useRegionFieldPreview(condition.data, baseId)
  const numeric = useQuery({ queryKey: ['packElevation', pack, heightSource],
    enabled: Boolean(pack && heightSource && palette && representation === 'map'), retry: false,
    queryFn: () => api.getPackElevation(pack!, heightSource!) })
  const numericInput = useMemo<ElevationInput | null>(() => numeric.data ? { kind: 'pack', blob: numeric.data, previewSide: 2048 } : null,
    [numeric.data])
  const terrainHeight = useRegionElevation(numericInput)
  const terrain = useElevationPreview(terrainHeight.ready?.kind === 'preview' ? terrainHeight.ready.raster : null,
    palette?.min ?? 0, palette?.max ?? 0, palette?.sea ?? 0, true)

  const base = useMemo(() => {
    if (!pack || !representation) return null
    if (representation !== 'map') return conditionPreview
    return !palette || numeric.isError || terrainHeight.failed ? { url: packTopoUrl(pack, original) } : terrain
  }, [representation, pack, original, palette, numeric.isError, terrainHeight.failed, terrain, conditionPreview])

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

  const onProbe = (ll: LonLat) => {
    setPin(ll)
    setProbe(null)
    setProbeError(null)
    if (!pack) return
    const seq = ++probeSeq.current
    setProbeLoading(true)
    api
      .probePack(pack, ll.lat, ll.lon)
      .then((data) => {
        if (probeSeq.current !== seq) return
        setProbe(data)
        setProbeLoading(false)
      })
      .catch((err: unknown) => {
        if (probeSeq.current !== seq) return
        setProbe(null)
        setProbeLoading(false)
        setProbeError(err instanceof Error ? err.message : String(err))
      })
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
      inspector={win && <ProbePanel point={pin} probe={probe} loading={fieldSource ? condition.isFetching : probeLoading}
        error={fieldSource ? condition.isError ? t('packs.conditions.unavailable') : null : probeError}
        condition={fieldSource ? { layer: baseId, source: fieldSource, window: win, raster: condition.data } : undefined} />}
      onClearPoint={pin ? () => { probeSeq.current += 1; setPin(null) } : undefined}
      layers={win && <RegionLayerPanel availableBase={availableBase}
        value={baseId} onSelect={setRequestedBase} compare={canCompare ? { original: showOriginal, onChange: setShowOriginal } : undefined}
        surfaceTemperatureOnly={temperatureSources.length === 1 && temperatureSources[0] === 'source'}
        notice={meta?.refined?.td_revision && !meta?.condition_layers?.grid.length ? 'missingGrid' : undefined}
        raster={representation ? { source: representation, choices, size: condition.data && `${condition.data.width} × ${condition.data.height}`,
          onChange: source => setRequestedSources(previous => ({ ...previous, [baseId]: source })) } : undefined}
        graticule={{ opacity: graticule, onChange: setGraticule }}
        rivers={rivers.data?.segs.length ? { opacity: riverOpacity, disabled: original, onChange: setRiverOpacity } : undefined} />}
      regionTools={win && <>
            {summary && <p className="break-words text-xs text-gray-400" title={t('packs.hint.source')}>
              {summary.branch ? `${summary.branch} · ` : ''}{summary.mtime}
            </p>}
            {pack && meta?.height_source && <PackElevationDownload key={`${pack}:${original ? 'input' : meta.height_source}`}
              pack={pack} source={original ? 'input' : meta.height_source} input={meta.input} summary={summary} />}
            {meta?.height_source === null && <p className="text-xs text-gray-400">{t('packs.export.noNumeric')}</p>}
            <TerrainCompute>{pack && !pack.startsWith('web-region-') && <RegionRefinementPanel source={{ kind: 'pack', pack }} globalReturn={regionReturn}
              resultUrl={(result) => {
                const params = new URLSearchParams(searchParams)
                params.set('pack', result)
                return `/packs?${params}`
              }} />}</TerrainCompute>
      </>}>
      {win ? <><PackMap window={win} base={base} loading={!base && (fieldSource ? !condition.isError : Boolean(heightSource))} context={context}
        rivers={original || !riverOpacity ? null : rivers.data ?? null} riverOpacity={riverOpacity}
        graticuleOpacity={graticule} pin={pin} onHover={setHover} onProbe={onProbe} />
        {fieldSource && condition.isError && <p role="alert" className="absolute left-3 top-3 z-[500] rounded border border-space-border bg-space-bg px-2 py-1 text-xs text-red-300">
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
