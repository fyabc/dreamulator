/**
 * PackViewerPage (0a-2 前端子地图页) — hi-res regional pack viewer for the
 * worldbuilding QA loop: browse terrain video-chain packs, hover for exact
 * lon/lat, click to probe cell values (height/biome/köppen/water/river).
 *
 * A URL with a global selection opens the browser's regional extract view.
 * Existing regional packs remain available through the local API.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api, packImageUrl, packTopoUrl } from '../api/client'
import { isStaticMode } from '../api/mode'
import MapHelpLink from '../components/map/MapHelpLink'
import { REGION_WINDOW_PARAM, readRegionWindow } from '../viewers/map/regionWindow'
import type { LonLat } from '../viewers/map/utils/mapCoords'
import PackMap from '../viewers/packs/PackMap'
import PackStatusBar from '../viewers/packs/PackStatusBar'
import ProbePanel from '../viewers/packs/ProbePanel'
import RegionalExtractView from '../viewers/packs/RegionalExtractView'
import PackElevationDownload from '../viewers/packs/PackElevationDownload'
import RegionRefinementPanel from '../viewers/packs/RegionRefinementPanel'
import TerrainCompute from '../viewers/packs/TerrainCompute'
import type { PackMeta, PackSummary, ProbeResult, RiverData } from '../viewers/packs/types'
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
    return <p role="alert" className="p-4 text-sm text-gray-400">{t('packs.export.invalidSelection')}</p>
  }
  return <ExistingPackViewer key={search.get('pack')} />
}

function ExistingPackViewer({ globalReturn, extractUrl }: { globalReturn?: string; extractUrl?: string }) {
  const { t } = useTranslation('map')
  const staticMode = isStaticMode()
  const { state } = useLocation()
  const regionReturn = globalReturn ?? (typeof state?.regionReturn === 'string' ? state.regionReturn : null)

  const [searchParams, setSearchParams] = useSearchParams()
  const [packs, setPacks] = useState<PackSummary[] | null>(null)
  const [pack, setPack] = useState<string | null>(searchParams.get('pack'))
  const [meta, setMeta] = useState<PackMeta | null>(null)
  const [summary, setSummary] = useState<PackSummary | null>(null)
  const [rivers, setRivers] = useState<RiverData | null>(null)
  const [baseId, setBaseId] = useState<string>('topo')
  const [showOriginal, setShowOriginal] = useState(false)
  const [graticuleOn, setGraticuleOn] = useState(true)
  const [hover, setHover] = useState<LonLat | null>(null)
  const [pin, setPin] = useState<LonLat | null>(null)
  const [probe, setProbe] = useState<ProbeResult | null>(null)
  const [probeLoading, setProbeLoading] = useState(false)
  const [probeError, setProbeError] = useState<string | null>(null)
  const probeSeq = useRef(0)

  useEffect(() => {
    if (staticMode) return
    api.listPacks().then(setPacks).catch(() => setPacks([]))
  }, [staticMode])

  // Deep link ?pack= — keep the URL in sync when the picker changes.
  const selectPack = (name: string | null) => {
    setPack(name)
    setMeta(null)
    setSummary(null)
    setRivers(null)
    setPin(null)
    setProbe(null)
    setProbeError(null)
    const next = new URLSearchParams(searchParams)
    if (name) next.set('pack', name)
    else next.delete('pack')
    setSearchParams(next, { replace: true, state })
  }

  useEffect(() => {
    if (!packs || !pack) return
    if (packs.some((p) => p.name === pack)) return
    // Stale ?pack= — fall back to the newest pack.
    selectPack(packs.length > 0 ? packs[0].name : null)
  }, [packs, pack])

  useEffect(() => {
    if (!pack) return
    let current = true
    api
      .getPackMeta(pack)
      .then((next) => { if (current) setMeta(next) })
      .catch(() => { if (current) setMeta(null) })
    api
      .getPackRivers(pack)
      .then((next) => { if (current) setRivers(next) })
      .catch(() => { if (current) setRivers(null) })
    return () => { current = false }
  }, [pack])

  useEffect(() => {
    if (!packs || !pack) return
    setSummary(packs.find((p) => p.name === pack) ?? null)
  }, [packs, pack])

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
  }, [availableBases])

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
          <TerrainCompute />
        </div>
      </div>
    )
  }

  const onProbe = (ll: LonLat) => {
    setPin(ll)
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

  return (
    <div className="flex flex-col h-[calc(100vh-56px)] md:h-screen">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2 bg-space-panel/80 border-b border-space-border">
        {regionReturn && (
          <Link to={regionReturn} className="text-xs text-neon-cyan hover:underline" title={t('packs.hint.back')}>
            {t('regionWindow.back')}
          </Link>
        )}
        {extractUrl && <Link to={extractUrl} state={{ regionReturn }} className="text-xs text-neon-cyan hover:underline">
          {t('packs.export.global')}
        </Link>}
        <label className="flex items-center gap-2">
          <span className="text-xs text-gray-500">{t('packs.pickPrompt')}</span>
          <select
            value={pack ?? ''}
            title={t('packs.hint.pick')}
            onChange={(e) => selectPack(e.target.value || null)}
            className="bg-space-surface border border-space-border rounded px-2 py-1 text-xs text-gray-200"
          >
            {packs === null && <option value="">…</option>}
            {packs?.length === 0 && <option value="">{t('packs.noPacks')}</option>}
            {packs?.map((p) => (
              <option key={p.name} value={p.name}>
                {p.world ?? p.name} · {p.center_lat}°, {p.center_lon}° · {Math.round(p.span_km)} km
              </option>
            ))}
          </select>
        </label>

        {summary && (
          <span className="ml-auto text-xs text-gray-600 font-mono" title={t('packs.hint.source')}>
            {summary.world}
            {summary.branch ? ` · ${summary.branch}` : ''} · {summary.mtime}
          </span>
        )}
        <div className={summary ? undefined : 'ml-auto'}>
          <MapHelpLink section="packs" label={t('packs.help')} />
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col bg-space-bg md:flex-row">
        {win && (
          <aside aria-label={t('label.layerSettings')}
            className="max-h-[38dvh] shrink-0 space-y-3 overflow-auto border-b border-space-border bg-space-panel p-3 md:max-h-none md:w-56 md:border-b-0 md:border-r">
            <h2 className="hidden text-xs font-semibold uppercase tracking-wide text-gray-500 md:block">
              {t('label.layerSettings')}
            </h2>
            <label className="flex items-center gap-2 md:block md:space-y-1">
              <span className="text-xs text-gray-400">{t('packs.base')}</span>
              <select
                value={baseId}
                title={t('packs.hint.base')}
                onChange={(e) => setBaseId(e.target.value)}
                className="rounded border border-space-border bg-space-surface px-2 py-1 text-xs text-gray-200 md:w-full"
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
            {canCompare && baseId === 'topo' && <label className="block text-xs text-gray-400">
              <span className="mr-2">{t('packs.refinement.compare')}</span>
              <select className="rounded border border-space-border bg-space-surface p-1 text-xs text-gray-200"
                value={showOriginal ? 'input' : 'result'} onChange={(event) => setShowOriginal(event.target.value === 'input')}>
                <option value="input">{t('packs.refinement.original')}</option>
                <option value="result">{t('packs.refinement.adopted')}</option>
              </select>
            </label>}
            {pack && meta?.height_source && <PackElevationDownload key={`${pack}:${original ? 'input' : meta.height_source}`}
              pack={pack} source={original ? 'input' : meta.height_source} input={meta.input} summary={summary} />}
            {meta?.height_source === null && <p className="text-xs text-gray-400">{t('packs.export.noNumeric')}</p>}
            <TerrainCompute>{pack && !pack.startsWith('web-region-') && <RegionRefinementPanel source={{ kind: 'pack', pack }} globalReturn={regionReturn}
              resultUrl={(result) => {
                const params = new URLSearchParams(searchParams)
                params.set('pack', result)
                return `/packs?${params}`
              }} />}</TerrainCompute>
          </aside>
        )}
        <div className="relative isolate min-h-0 min-w-0 flex-1">
          {win ? (
            <>
              <PackMap
                window={win}
                base={base}
                rivers={original ? null : rivers}
                graticuleOn={graticuleOn}
                pin={pin}
                onHover={setHover}
                onProbe={onProbe}
              />
              <div className="absolute top-3 right-3 z-[500] flex flex-col gap-2 items-end pointer-events-auto">
                <ProbePanel
                  point={pin}
                  probe={probe}
                  loading={probeLoading}
                  error={probeError}
                  meta={meta}
                  spanKm={summary?.span_km ?? null}
                />
              </div>
            </>
          ) : (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-gray-500">
              {packs === null ? '…' : t('packs.noMeta')}
            </div>
          )}
        </div>
      </div>

      {/* Status bar */}
      {win && <PackStatusBar hover={hover} window={win} />}
    </div>
  )
}
