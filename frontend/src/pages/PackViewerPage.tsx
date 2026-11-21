/**
 * PackViewerPage (0a-2 前端子地图页) — hi-res regional pack viewer for the
 * worldbuilding QA loop: browse terrain video-chain packs, hover for exact
 * lon/lat, click to probe cell values (height/biome/köppen/water/river).
 *
 * A URL with a global selection opens the browser's regional extract view.
 * Existing regional packs remain available through the local API.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api, ApiError, packImageUrl, packTopoUrl } from '../api/client'
import { isStaticMode } from '../api/mode'
import AtlasIcon from '../components/AtlasIcon'
import MapHelpLink from '../components/map/MapHelpLink'
import { REGION_WINDOW_PARAM, readRegionWindow } from '../viewers/map/regionWindow'
import type { LonLat } from '../viewers/map/utils/mapCoords'
import PackMap from '../viewers/packs/PackMap'
import PackStatusBar from '../viewers/packs/PackStatusBar'
import ProbePanel from '../viewers/packs/ProbePanel'
import RegionalExtractView from '../viewers/packs/RegionalExtractView'
import RegionMapWorkspace from '../viewers/packs/RegionMapWorkspace'
import PackElevationDownload from '../viewers/packs/PackElevationDownload'
import RegionRefinementPanel from '../viewers/packs/RegionRefinementPanel'
import TerrainCompute from '../viewers/packs/TerrainCompute'
import type { PackMeta, PackSummary, ProbeResult } from '../viewers/packs/types'
import type { PackWindow } from '../viewers/packs/packCoords'

interface BaseOption {
  id: string
  path: string
  /** Required legs key, or null when every pack has it. */
  needs: keyof PackSummary['legs'] | null
  /** Server-rendered composite endpoint instead of a pack file. */
  endpoint?: 'topo'
}

const BASE_OPTIONS: BaseOption[] = [
  { id: 'topo', path: '', needs: null, endpoint: 'topo' },
  { id: 'preview', path: 'color/preview.png', needs: 'color' },
  { id: 'albedo', path: 'color/albedo.png', needs: 'color' },
  { id: 'color', path: 'input/color.png', needs: null },
  { id: 'koppen', path: 'input/koppen.png', needs: null },
  { id: 'biome', path: 'input/biome.png', needs: null },
]

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

export default function PackViewerPage() {
  const { t } = useTranslation('map')
  const [search] = useSearchParams()
  const { state } = useLocation()
  const world = search.get('world')
  const planet = search.get('planet')
  const branch = search.get('branch') || null
  const radiusKm = Number(search.get('radius'))
  const rawWindow = search.get(REGION_WINDOW_PARAM)
  const selection = readRegionWindow(rawWindow, radiusKm)
  if (world && planet && selection) {
    const globalParams = new URLSearchParams({ [REGION_WINDOW_PARAM]: rawWindow! })
    if (branch) globalParams.set('branch', branch)
    const view = search.get('view') === 'globe' ? 'globe' : 'map'
    const globalReturn = typeof state?.regionReturn === 'string' ? state.regionReturn
      : `/worlds/${encodeURIComponent(world)}/${view}/${encodeURIComponent(planet)}?${globalParams}`
    if (!search.has('pack') || isStaticMode()) {
      return <RegionalExtractView key={search.toString()} world={world} planet={planet} branch={branch}
        radiusKm={radiusKm} selection={selection} globalReturn={globalReturn} regionParams={search} />
    }
    const params = new URLSearchParams(search)
    params.delete('pack')
    return <ExistingPackViewer key={search.get('pack')} globalReturn={globalReturn} extractUrl={`/packs?${params}`} />
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

function ExistingPackViewer({ globalReturn, extractUrl }: { globalReturn?: string; extractUrl?: string }) {
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
  const [baseId, setBaseId] = useState<string>('topo')
  const [showOriginal, setShowOriginal] = useState(false)
  const [graticuleOn, setGraticuleOn] = useState(true)
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
  const canCompare = meta?.height_source === 'refined-out'
  const original = canCompare && showOriginal && baseId === 'topo'

  const availableBases = useMemo<BaseOption[]>(() => {
    if (!summary) return BASE_OPTIONS.filter((b) => b.needs === null)
    return BASE_OPTIONS.filter((b) => b.needs === null || summary.legs[b.needs])
  }, [summary])

  useEffect(() => {
    if (!availableBases.some((b) => b.id === baseId)) {
      setBaseId(availableBases[0]?.id ?? 'color')
    }
  }, [availableBases, baseId])

  const base = useMemo(() => {
    const opt = availableBases.find((b) => b.id === baseId)
    if (!opt || !pack) return null
    return { url: opt.endpoint === 'topo' ? packTopoUrl(pack, original) : packImageUrl(pack, opt.path) }
  }, [availableBases, baseId, pack, original])

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

  const checkboxCls =
    'flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-200 cursor-pointer select-none'
  const missingPack = metaQuery.error instanceof ApiError && metaQuery.error.status === 404
  const hasEntryError = pack ? metaQuery.isError : packs.isError
  const entryMessage = pack
    ? missingPack ? 'packs.entry.notFound' : metaQuery.isError ? 'packs.noMeta' : 'status.loading'
    : packs.isPending ? 'packs.entry.loadingList' : packs.isError ? 'packs.entry.listFailed'
      : packs.data?.length ? 'packs.entry.chooseHint' : 'packs.noPacks'
  const openWorlds = (!pack || missingPack) && packs.isSuccess && !packs.data.length
  const retry = pack && !missingPack && metaQuery.isError ? metaQuery.refetch
    : !pack && packs.isError ? packs.refetch : null

  return (
    <div className="flex min-h-[calc(100dvh-56px)] flex-col md:h-[100dvh]">
      <header className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-2 border-b border-space-border bg-space-panel px-3 py-2 sm:px-4">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-4">
          <h1 className="text-sm font-semibold text-gray-200">{t('packs.pickPrompt')}</h1>
          {regionReturn && <Link to={regionReturn} title={t('packs.hint.back')}
            className="inline-flex min-h-9 items-center text-xs text-neon-cyan hover:underline">{t('regionWindow.back')}</Link>}
          {extractUrl && <Link to={extractUrl} state={{ regionReturn }}
            className="inline-flex min-h-9 items-center text-xs text-neon-cyan hover:underline">{t('packs.export.global')}</Link>}
        </div>
        <MapHelpLink section="packs" label={t('packs.help')} />
        <div className="flex w-full min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
          <select
            value={pack ?? ''}
            aria-label={t('packs.entry.choose')}
            title={t('packs.hint.pick')}
            onChange={(event) => selectPack(event.target.value || null)}
            disabled={!packs.data?.length}
            className="min-h-11 w-full min-w-0 rounded border border-space-border bg-space-surface px-2 text-sm text-gray-200 disabled:text-gray-400 sm:w-auto sm:max-w-full md:min-h-8 md:text-xs"
          >
            <option value="">{t('packs.entry.choose')}</option>
            {pack && !summary && <option value={pack}>{pack}</option>}
            {packs.data?.map((item) => (
              <option key={item.name} value={item.name}>
                {item.world ?? item.name} · {item.center_lat}°, {item.center_lon}° · {Math.round(item.span_km)} km
              </option>
            ))}
          </select>
          {summary && <p className="hidden break-words text-xs text-gray-400 sm:block" title={t('packs.hint.source')}>
            {summary.branch ? `${summary.branch} · ` : ''}{summary.mtime}
          </p>}
          {pack && packs.isError && <button type="button" onClick={() => void packs.refetch()}
            className="min-h-9 text-xs text-neon-cyan hover:underline">{t('packs.entry.retryList')}</button>}
        </div>
      </header>
      {win ? (
        <RegionMapWorkspace toolsLabel={t('label.layerSettings')} status={<PackStatusBar hover={hover} window={win} />} tools={<>
            <h2 className="text-sm font-semibold text-gray-200">
              {t('label.layerSettings')}
            </h2>
            {canCompare && baseId === 'topo' && <label className="flex flex-wrap items-center gap-2 text-xs text-gray-400">
              <span>{t('packs.refinement.compare')}</span>
              <select className="min-h-11 max-w-full rounded border border-space-border bg-space-surface p-1 text-xs text-gray-200 md:min-h-8"
                value={showOriginal ? 'input' : 'result'} onChange={(event) => setShowOriginal(event.target.value === 'input')}>
                <option value="input">{t('packs.refinement.original')}</option>
                <option value="result">{t('packs.refinement.adopted')}</option>
              </select>
            </label>}
            <label className="flex flex-wrap items-center gap-2 md:block md:space-y-1">
              <span className="text-xs text-gray-400">{t('packs.base')}</span>
              <select
                value={baseId}
                title={t('packs.hint.base')}
                onChange={(e) => setBaseId(e.target.value)}
                className="min-h-11 max-w-full rounded border border-space-border bg-space-surface px-2 text-xs text-gray-200 md:min-h-8 md:w-full"
              >
                {availableBases.map((b) => (
                  <option key={b.id} value={b.id}>
                    {t(`packs.baseOptions.${b.id}`)}
                  </option>
                ))}
              </select>
            </label>
            <label className={checkboxCls} title={t('packs.hint.graticule')}>
              <input type="checkbox" checked={graticuleOn} onChange={(e) => setGraticuleOn(e.target.checked)} />
              {t('packs.graticule')}
            </label>
            {summary && <p className="break-words text-xs text-gray-400 sm:hidden" title={t('packs.hint.source')}>
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
              <PackMap
                window={win}
                base={base}
                rivers={original ? null : rivers.data ?? null}
                graticuleOn={graticuleOn}
                pin={pin}
                onHover={setHover}
                onProbe={onProbe}
              />
              <div className={`absolute bottom-3 right-3 z-[500] max-h-[calc(100%-1.5rem)] max-w-[calc(100%-1.5rem)] overflow-auto md:bottom-auto md:top-3 ${pin ? '' : 'hidden md:block'}`}>
                {pin && <button type="button" aria-label={t('packs.entry.closeProbe')}
                  className="mb-1 ml-auto flex size-11 items-center justify-center rounded border border-space-border bg-space-panel text-gray-200 md:size-8"
                  onClick={() => {
                    probeSeq.current += 1
                    setPin(null)
                  }}><AtlasIcon name="close" className="size-4" /></button>}
                <ProbePanel
                  point={pin}
                  probe={probe}
                  loading={probeLoading}
                  error={probeError}
                  meta={meta}
                  spanKm={summary?.span_km ?? null}
                />
              </div>
        </RegionMapWorkspace>
      ) : (
        <div className="max-w-lg space-y-2 px-3 py-5 text-sm text-gray-300 sm:px-4">
          <p role={hasEntryError ? 'alert' : 'status'}>{t(entryMessage)}</p>
          {retry && <button type="button" onClick={() => void retry()} className="min-h-11 text-neon-cyan hover:underline">
            {t('packs.export.retry')}
          </button>}
          {openWorlds && <Link to="/worlds" className="inline-flex min-h-11 items-center text-neon-cyan hover:underline">
            {t('packs.entry.openWorlds')}
          </Link>}
        </div>
      )}
    </div>
  )
}
