/**
 * PackViewerPage (0a-2 前端子地图页) — hi-res regional pack viewer for the
 * worldbuilding QA loop: browse terrain video-chain packs, hover for exact
 * lon/lat, click to probe cell values (height/biome/köppen/water/river).
 *
 * API-mode only by design: packs are gitignored local artifacts and never
 * reach the static export, so this page deliberately skips the staticClient
 * mirror — the static guard below is the intended degradation (same pattern
 * as the narrate SSE endpoints).
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api, packImageUrl, packTopoUrl } from '../api/client'
import { isStaticMode } from '../api/mode'
import MapHelpLink from '../components/map/MapHelpLink'
import type { LonLat } from '../viewers/map/utils/mapCoords'
import PackMap from '../viewers/packs/PackMap'
import PackStatusBar from '../viewers/packs/PackStatusBar'
import ProbePanel from '../viewers/packs/ProbePanel'
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
  }
}

export default function PackViewerPage() {
  const { t } = useTranslation('map')
  const staticMode = isStaticMode()
  const { state } = useLocation()
  const regionReturn = typeof state?.regionReturn === 'string' ? state.regionReturn : null

  const [searchParams, setSearchParams] = useSearchParams()
  const [packs, setPacks] = useState<PackSummary[] | null>(null)
  const [pack, setPack] = useState<string | null>(searchParams.get('pack'))
  const [meta, setMeta] = useState<PackMeta | null>(null)
  const [summary, setSummary] = useState<PackSummary | null>(null)
  const [rivers, setRivers] = useState<RiverData | null>(null)
  const [baseId, setBaseId] = useState<string>('topo')
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
    setPin(null)
    setProbe(null)
    setProbeError(null)
    setSearchParams(name ? { pack: name } : {}, { replace: true, state })
  }

  useEffect(() => {
    if (!packs || !pack) return
    if (packs.some((p) => p.name === pack)) return
    // Stale ?pack= — fall back to the newest pack.
    selectPack(packs.length > 0 ? packs[0].name : null)
  }, [packs, pack])

  useEffect(() => {
    if (!pack) return
    api
      .getPackMeta(pack)
      .then(setMeta)
      .catch(() => setMeta(null))
    api
      .getPackRivers(pack)
      .then(setRivers)
      .catch(() => setRivers(null))
  }, [pack])

  useEffect(() => {
    if (!packs || !pack) return
    setSummary(packs.find((p) => p.name === pack) ?? null)
  }, [packs, pack])

  const win = useMemo(() => (meta ? windowOf(meta) : null), [meta])

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
    return { url: opt.endpoint === 'topo' ? packTopoUrl(pack) : packImageUrl(pack, opt.path) }
  }, [availableBases, baseId, pack])

  // Static mode: the pack root is a local-only directory — nothing to show.
  // All hooks have run by this point, so the conditional return is safe.
  if (staticMode) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="bg-space-panel border border-space-border rounded-lg p-6 text-sm text-gray-400 max-w-md">
          <div className="flex items-center justify-between gap-3 mb-2">
            <h1 className="font-semibold text-gray-200">{t('packs.pickPrompt')}</h1>
            <MapHelpLink section="packs" label={t('packs.help')} />
          </div>
          <p>{t('packs.staticModeHint')}</p>
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
            className="flex shrink-0 flex-wrap items-center gap-3 border-b border-space-border bg-space-panel p-3 md:block md:w-48 md:space-y-3 md:border-b-0 md:border-r">
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
          </aside>
        )}
        <div className="relative isolate min-h-0 min-w-0 flex-1">
          {win ? (
            <>
              <PackMap
                window={win}
                base={base}
                rivers={rivers}
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
