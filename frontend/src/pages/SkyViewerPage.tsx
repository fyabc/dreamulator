/** SkyViewerPage — the observer's-sky view (`/worlds/:worldName/sky/:bodyId?`),
 *  Stellarium posture: the sky fills the whole viewport and every control is
 *  chrome that appears on pointer activity and fades when idle.  State lives
 *  in URL search params (?from=&lat=&lon=&at=&branch=&mode=&look=&fov=&grids=&panels=,
 *  replace writes); the instant commits on gesture end, look/fov the same.
 *  API-only by design (parameterized engine query): static mode renders a
 *  hint panel (packs precedent).
 */

import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { isStaticMode } from '../api/mode'
import SkyChart from '../viewers/sky/SkyChart'
import SkyInspector from '../viewers/sky/SkyInspector'
import SkyPanChart from '../viewers/sky/SkyPanChart'
import SkyRiseSetTable from '../viewers/sky/SkyRiseSetTable'
import SkyTimeControl from '../viewers/sky/SkyTimeControl'
import SkyBelowHorizonList from '../viewers/sky/SkyBelowHorizonList'
import { SkyDisplayDialog, SkyObserverDialog, type SkyPanel } from '../viewers/sky/SkyDialogs'
import { observerCandidates } from '../viewers/sky/observer'
import { clampLook, type LookDirection } from '../viewers/sky/panProjector'
import type { GridToggles } from '../viewers/sky/skyGrids'
import { useElementSize } from '../viewers/sky/useElementSize'
import { useIdleChrome } from '../viewers/sky/useIdleChrome'
import { useSkyData } from '../viewers/sky/useSkyData'
import { useSkyTime } from '../viewers/sky/useSkyTime'

function numberParam(params: URLSearchParams, key: string, fallback: number): number {
  const raw = params.get(key)
  if (raw === null) return fallback
  const value = Number(raw)
  return Number.isFinite(value) ? value : fallback
}

const DEFAULT_LOOK: LookDirection = { azDeg: 0, altDeg: 12, fovDeg: 90 }

function lookFromParams(params: URLSearchParams): LookDirection {
  const raw = params.get('look')
  const parts = raw?.split(',').map(Number) ?? []
  return clampLook({
    azDeg: Number.isFinite(parts[0]) ? parts[0] : DEFAULT_LOOK.azDeg,
    altDeg: Number.isFinite(parts[1]) ? parts[1] : DEFAULT_LOOK.altDeg,
    fovDeg: numberParam(params, 'fov', DEFAULT_LOOK.fovDeg),
  })
}

function csvParam(params: URLSearchParams, key: string): Set<string> {
  const raw = params.get(key)
  return new Set(raw ? raw.split(',').filter(Boolean) : [])
}

export default function SkyViewerPage() {
  const { worldName, bodyId } = useParams()
  const { t } = useTranslation(['sky', 'common'])
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const staticMode = isStaticMode()
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [dialog, setDialog] = useState<'none' | 'observer' | 'display'>('none')
  const { visible: chromeVisible, pin: chromePin, hold: chromeHold } = useIdleChrome()

  const branch = searchParams.get('branch')
  const lat = numberParam(searchParams, 'lat', 0)
  const lon = numberParam(searchParams, 'lon', 0)
  const mode: 'pan' | 'disc' = searchParams.get('mode') === 'disc' ? 'disc' : 'pan'
  const [look, setLookState] = useState<LookDirection>(() => lookFromParams(searchParams))
  // Without an explicit ?look=, the first result aims the pan view at the
  // brightest above-horizon body (altitude capped so the sky patch has
  // context); a bare north-facing default can be an honestly empty sector.
  const aimedRef = useRef(searchParams.has('look'))
  const setLook = (next: LookDirection) => {
    aimedRef.current = true
    setLookState(next)
  }
  const grids: GridToggles = useMemo(
    () => ({
      altAz: csvParam(searchParams, 'grids').has('alt'),
      equatorial: csvParam(searchParams, 'grids').has('eq'),
      ecliptic: csvParam(searchParams, 'grids').has('ecl'),
    }),
    [searchParams],
  )
  // One right-side panel at a time (radio behaviour); the param keeps the
  // first token so legacy CSV links still resolve.
  const activePanel: SkyPanel | null = useMemo(() => {
    const raw = searchParams.get('panels')?.split(',').filter(Boolean)[0]
    return raw === 'below' || raw === 'almanac' ? raw : null
  }, [searchParams])

  const catalogQuery = useQuery({
    queryKey: ['system-catalog', worldName, branch],
    queryFn: () => api.getSystemCatalog(worldName!, branch),
    enabled: !!worldName && !staticMode,
    retry: false,
  })
  const catalog = catalogQuery.data

  // The universe setting is static per (world, branch): fetch once, rotate
  // client-side — look-around stays fetch-free.
  const backgroundQuery = useQuery({
    queryKey: ['sky-background', worldName, branch],
    queryFn: () => api.getSkyBackground(worldName!, branch),
    enabled: !!worldName && !staticMode,
    retry: false,
    staleTime: Infinity,
  })
  const background = backgroundQuery.data ?? null
  const backgroundOn = searchParams.get('bg') !== '0'

  const observerId = useMemo(() => {
    const from = searchParams.get('from')
    if (from) return from
    const target = catalog?.target_body_id
    return typeof target === 'string' ? target : null
  }, [searchParams, catalog])

  const time = useSkyTime()
  const data = useSkyData({
    worldName: worldName ?? '',
    observerId,
    branch,
    lat,
    lon,
    atCommitted: time.atCommitted,
    atLive: time.atLive,
    interacting: time.interacting,
  })

  const solarDay = data.display?.solar_day_days ?? null
  time.setSolarDay(solarDay)
  const { ref: skyRef, size } = useElementSize<HTMLDivElement>()

  // Hold the chrome while a dialog is open.
  useEffect(() => {
    chromeHold(dialog !== 'none')
  }, [dialog, chromeHold])

  // First-result aim (see aimedRef comment above).  Horizon-grazing winners
  // (a star rising at +1° is the brightest thing but makes an empty view)
  // yield to the brightest body at a comfortable altitude.
  useEffect(() => {
    if (aimedRef.current || !data.display) return
    aimedRef.current = true
    const above = [...data.display.targets]
      .filter((row) => row.altitude_deg > 0)
      .sort((a, b) => a.apparent_magnitude - b.apparent_magnitude)
    const brightest = above.find((row) => row.altitude_deg >= 10) ?? above[0]
    if (brightest) {
      setLookState(
        clampLook({
          azDeg: brightest.azimuth_deg,
          altDeg: Math.min(Math.max(brightest.altitude_deg, 0), 60),
          fovDeg: look.fovDeg,
        }),
      )
    }
    // Aims once on the first result; look.fovDeg is read, not tracked.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.display])

  const setParam = (key: string, value: string | null) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value === null || value === '') next.delete(key)
        else next.set(key, value)
        return next
      },
      { replace: true },
    )
  }

  const observerOptions = useMemo(() => (catalog ? observerCandidates(catalog) : []), [catalog])

  const selectBody = (id: string) => {
    navigate(`/worlds/${worldName}/sky/${id}${window.location.search}`, { replace: true })
  }
  const deselectBody = () => {
    navigate(`/worlds/${worldName}/sky${window.location.search}`, { replace: true })
  }

  const commitLook = () => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('look', `${look.azDeg.toFixed(1)},${look.altDeg.toFixed(1)}`)
        next.set('fov', look.fovDeg.toFixed(0))
        return next
      },
      { replace: true },
    )
  }

  const setGrids = (next: GridToggles) => {
    const csv = [
      next.altAz ? 'alt' : '',
      next.equatorial ? 'eq' : '',
      next.ecliptic ? 'ecl' : '',
    ].filter(Boolean).join(',')
    setParam('grids', csv || null)
  }

  const setPanel = (panel: SkyPanel | null) => {
    setParam('panels', panel)
  }

  const belowRows = useMemo(
    () => (data.display ? data.display.targets.filter((row) => row.altitude_deg <= 0) : []),
    [data.display],
  )

  const safeLook = clampLook(look)

  // All hooks above; the static-mode guard renders after them (packs pattern).
  if (staticMode) {
    return (
      <div className="flex items-center justify-center min-h-[60vh] px-6">
        <div className="max-w-md text-center text-sm text-gray-400 leading-relaxed">
          <div className="text-3xl mb-3">✨</div>
          {t('sky:staticModeHint')}
        </div>
      </div>
    )
  }

  const chromeClass = `transition-opacity duration-300 ${
    chromeVisible ? 'opacity-100' : 'opacity-0 pointer-events-none'
  }`

  return (
    <Suspense fallback={<div className="p-6 text-sm text-gray-500">{t('sky:status.loading')}</div>}>
      <div className="fixed inset-0 z-40 bg-[#030308] overflow-hidden">
        {/* The sky, filling everything */}
        <div ref={skyRef} className="absolute inset-0">
          {data.error ? (
            <div className="m-4 p-3 rounded bg-red-900/20 border border-red-500/30 text-sm text-red-300">
              {t('sky:status.error')}: {data.error.message}
            </div>
          ) : !data.display || (mode === 'pan' && !size) ? (
            <div className="w-full h-full flex items-center justify-center">
              <div className="text-sm text-gray-500 animate-pulse">{t('sky:status.loading')}</div>
            </div>
          ) : mode === 'pan' ? (
            <SkyPanChart
              result={data.display}
              catalog={catalog}
              width={size!.width}
              height={size!.height}
              look={look}
              onLookChange={setLook}
              onLookCommit={commitLook}
              grids={grids}
              background={background}
              backgroundOn={backgroundOn}
              selectedId={bodyId ?? null}
              hoveredId={hoveredId}
              onHover={setHoveredId}
              onSelect={selectBody}
              onBackgroundSelect={deselectBody}
            />
          ) : (
            <div className="absolute inset-0 p-4 md:p-8">
              <SkyChart
                result={data.display}
                catalog={catalog}
                selectedId={bodyId ?? null}
                hoveredId={hoveredId}
                onHover={setHoveredId}
                onSelect={selectBody}
                look={look}
                grids={grids}
                background={background}
                backgroundOn={backgroundOn}
              />
            </div>
          )}
        </div>

        {/* Right-side column: the selected-body info panel and the one open
            panel popup, translucent so the sky stays visible through them. */}
        {(bodyId || activePanel) && (
          <div className="absolute top-3 right-3 flex flex-col items-end gap-2 max-h-[calc(100vh-8rem)]">
            {bodyId && data.display && (
              <div
                className="relative w-64 max-h-full overflow-y-auto border border-space-border/60 bg-space-panel/55 backdrop-blur-md rounded-lg p-3 shadow-lg"
                onPointerEnter={() => chromePin(true)}
                onPointerLeave={() => chromePin(false)}
              >
                <button
                  type="button"
                  onClick={deselectBody}
                  className="absolute top-2 right-2 w-5 h-5 rounded text-gray-500 hover:text-gray-200 hover:bg-space-surface text-xs leading-none"
                  aria-label={t('sky:info.close')}
                  title={t('sky:info.close')}
                >
                  ✕
                </button>
                <SkyInspector result={data.display} selectedId={bodyId} />
              </div>
            )}
            {activePanel && data.display && (
              <div
                className="relative w-[min(560px,55vw)] max-h-full overflow-y-auto border border-space-border/60 bg-space-panel/55 backdrop-blur-md rounded-lg p-3 shadow-lg"
                onPointerEnter={() => chromePin(true)}
                onPointerLeave={() => chromePin(false)}
              >
                <div className="flex items-center justify-between mb-1">
                  <div className="text-xs font-semibold text-neon-cyan">{t(`sky:panels.${activePanel}`)}</div>
                  <button
                    type="button"
                    onClick={() => setPanel(null)}
                    className="w-5 h-5 rounded text-gray-500 hover:text-gray-200 hover:bg-space-surface text-xs leading-none"
                    aria-label={t('sky:info.close')}
                    title={t('sky:info.close')}
                  >
                    ✕
                  </button>
                </div>
                {activePanel === 'almanac' ? (
                  <SkyRiseSetTable
                    result={data.display}
                    selectedId={bodyId ?? null}
                    onSelect={selectBody}
                    defaultOpen
                  />
                ) : (
                  <SkyBelowHorizonList rows={belowRows} selectedId={bodyId ?? null} />
                )}
              </div>
            )}
          </div>
        )}

        {/* Chrome: back + left-edge toolbar + bottom time bar + readout */}
        <div className={chromeClass}>
          <Link
            to={`/worlds/${worldName}`}
            className="absolute top-3 left-3 w-8 h-8 flex items-center justify-center rounded-lg border border-space-border bg-space-panel/85 backdrop-blur text-gray-400 hover:text-neon-cyan text-sm transition-colors"
            title={t('sky:ui.back')}
          >
            ←
          </Link>

          {/* Left-edge toolbar (slide-out on hover like Stellarium's) */}
          <div
            className="absolute left-3 top-1/2 -translate-y-1/2 flex flex-col gap-2"
            onPointerEnter={() => chromePin(true)}
            onPointerLeave={() => chromePin(false)}
          >
            {(
              [
                ['observer', '📍', t('sky:dialog.observer.title')],
                ['display', '🧭', t('sky:dialog.display.title')],
              ] as const
            ).map(([key, icon, title]) => (
              <button
                key={key}
                type="button"
                onClick={() => setDialog(dialog === key ? 'none' : key)}
                className={`w-9 h-9 flex items-center justify-center rounded-lg border text-base transition-colors ${
                  dialog === key
                    ? 'bg-neon-cyan/15 border-neon-cyan/40 text-neon-cyan'
                    : 'border-space-border bg-space-panel/85 backdrop-blur text-gray-400 hover:text-gray-100'
                }`}
                title={title}
              >
                {icon}
              </button>
            ))}
            <a
              href="/help#sky-viewer"
              target="_blank"
              rel="noreferrer"
              className="w-9 h-9 flex items-center justify-center rounded-lg border border-space-border bg-space-panel/85 backdrop-blur text-gray-400 hover:text-gray-100 text-base"
              title={t('sky:ui.help')}
            >
              ?
            </a>
          </div>

          {/* Dialogs next to the toolbar */}
          {dialog === 'observer' && (
            <div className="absolute left-16 top-1/2 -translate-y-1/2">
              <SkyObserverDialog
                observerOptions={observerOptions}
                observerId={observerId}
                onSelectObserver={(id) => setParam('from', id)}
                lat={lat}
                lon={lon}
                onLat={(v) => Number.isFinite(v) && setParam('lat', String(v))}
                onLon={(v) => Number.isFinite(v) && setParam('lon', String(v))}
                worldName={worldName ?? ''}
                branch={branch}
                onSelectBranch={(b) => setParam('branch', b)}
                spinSource={data.display?.spin_source ?? null}
                solarDayDays={solarDay}
                onPointerEnter={() => chromePin(true)}
                onPointerLeave={() => chromePin(false)}
              />
            </div>
          )}
          {dialog === 'display' && (
            <div className="absolute left-16 top-1/2 -translate-y-1/2">
              <SkyDisplayDialog
                mode={mode}
                onMode={(m) => setParam('mode', m === 'pan' ? null : m)}
                grids={grids}
                onGrids={setGrids}
                backgroundOn={backgroundOn}
                onBackgroundOn={(on) => setParam('bg', on ? null : '0')}
                activePanel={activePanel}
                onSelectPanel={setPanel}
                onPointerEnter={() => chromePin(true)}
                onPointerLeave={() => chromePin(false)}
              />
            </div>
          )}

          {/* Bottom time bar (Stellarium's bottom strip) */}
          <div
            className="absolute bottom-4 left-1/2 -translate-x-1/2 w-[calc(100vw-1.5rem)] sm:w-[min(760px,calc(100vw-15rem))] border border-space-border bg-space-panel/90 backdrop-blur rounded-xl px-3 sm:px-4 py-2 shadow-xl"
            onPointerEnter={() => chromePin(true)}
            onPointerLeave={() => chromePin(false)}
          >
            <SkyTimeControl time={time} solarDayDays={solarDay} />
          </div>

          {/* View readout + hint (bottom-left, quiet like Stellarium's location line) */}
          {mode === 'pan' && (
            <div className="absolute bottom-4 left-3 pointer-events-none space-y-0.5 text-[10px] hidden sm:block max-w-[13rem]">
              <div className="font-mono tabular-nums text-gray-400 bg-space-panel/70 backdrop-blur rounded px-1.5 py-0.5">
                {t('sky:chart.azimuth')} {safeLook.azDeg.toFixed(0)}° · {t('sky:chart.altitude')}{' '}
                {safeLook.altDeg >= 0 ? '+' : ''}
                {safeLook.altDeg.toFixed(0)}° · {t('sky:pan.fov')} {safeLook.fovDeg.toFixed(0)}°
              </div>
              <div className="text-gray-600 bg-space-panel/70 backdrop-blur rounded px-1.5 py-0.5">
                {t('sky:pan.hint')}
              </div>
            </div>
          )}
        </div>

      </div>
    </Suspense>
  )
}
