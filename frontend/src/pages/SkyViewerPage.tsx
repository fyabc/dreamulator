/** SkyViewerPage — the observer's-sky view (`/worlds/:worldName/sky/:bodyId?`),
 *  The sky fills the viewport. Observation status stays visible; controls
 *  appear on pointer activity and fade when idle. State lives
 *  in URL search params (?from=&lat=&lon=&at=&branch=&mode=&look=&fov=&grids=&panels=,
 *  replace writes); the instant commits on gesture end, look/fov the same.
 *  API-only by design (parameterized engine query): static mode renders a
 *  hint panel (packs precedent).
 */

import { Suspense, useEffect, useMemo, useRef, useState, type FocusEvent, type PointerEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import { isStaticMode } from '../api/mode'
import AtlasIcon from '../components/AtlasIcon'
import { useCelestialName } from '../i18n/celestialNames'
import SkyChart from '../viewers/sky/SkyChart'
import SkyInspector from '../viewers/sky/SkyInspector'
import SkyObjectInspector from '../viewers/sky/SkyObjectInspector'
import SkyPanChart from '../viewers/sky/SkyPanChart'
import SkyRiseSetTable from '../viewers/sky/SkyRiseSetTable'
import SkyTimeControl from '../viewers/sky/SkyTimeControl'
import { epochOffset } from '../viewers/sky/timeFormat'
import SkyBelowHorizonList from '../viewers/sky/SkyBelowHorizonList'
import { SkyDisplayDialog, SkyObserverDialog, type SkyPanel } from '../viewers/sky/SkyDialogs'
import { observerCandidates } from '../viewers/sky/observer'
import { clampLook, type LookDirection } from '../viewers/sky/panProjector'
import type { GridToggles } from '../viewers/sky/skyGrids'
import type { SkyCatalog } from '../viewers/sky/types'
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

const DEFAULT_LOOK: LookDirection = { azDeg: 0, altDeg: 50, fovDeg: 110 }
const iconButton = 'inline-flex shrink-0 items-center justify-center rounded-lg text-slate-300 hover:bg-space-surface hover:text-white'
const panelShell = 'min-h-0 overflow-y-auto overscroll-contain rounded-lg border border-space-border bg-space-panel/95 p-3'

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
  const { t } = useTranslation('sky')
  const celestialName = useCelestialName(worldName)
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const staticMode = isStaticMode()
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  /** Selected universe-setting object (authored star / DSO) — a namespace
   *  disjoint from body ids; the two selections are mutually exclusive. */
  const [bgId, setBgId] = useState<string | null>(null)
  const [dialog, setDialog] = useState<'none' | 'observer' | 'display'>('none')
  const [controlsHidden, setControlsHidden] = useState(false)
  const [controlsHovered, setControlsHovered] = useState(false)
  const [controlsFocused, setControlsFocused] = useState(false)
  const dialogTrigger = useRef<HTMLButtonElement | null>(null)

  const branch = searchParams.get('branch')
  const lat = numberParam(searchParams, 'lat', 0)
  const lon = numberParam(searchParams, 'lon', 0)
  const mode: 'pan' | 'disc' = searchParams.get('mode') === 'disc' ? 'disc' : 'pan'
  const [look, setLookState] = useState<LookDirection>(() => lookFromParams(searchParams))
  // Without an explicit ?look=, the first result chooses the azimuth of the
  // brightest suitable body while keeping the horizon in the default frame.
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
  const catalog: SkyCatalog | undefined = catalogQuery.data
  const referenceEpoch = catalog?.reference_epoch

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

  // The civilization layer's star lore (asterism figures + culture star
  // names), joined against the background catalogue by id client-side.  A
  // world without cultures 404s — that is normal, not an error state: the
  // toggle and the layer simply stay hidden.
  const cultureQuery = useQuery({
    queryKey: ['sky-culture', worldName, branch],
    queryFn: () => api.getSkyCulture(worldName!, branch),
    enabled: !!worldName && !staticMode,
    retry: false,
    staleTime: Infinity,
  })
  const culture = cultureQuery.data ?? null
  const hasCulture = (culture?.cultures.length ?? 0) > 0
  const cultureOn = searchParams.get('cul') !== '0'

  const observerId = useMemo(() => {
    const from = searchParams.get('from')
    if (from) return from
    const target = catalog?.target_body_id
    return typeof target === 'string' ? target : null
  }, [searchParams, catalog])

  const time = useSkyTime()
  const data = useSkyData({
    worldName: worldName ?? '',
    observerId: staticMode ? null : observerId,
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
  const error = catalogQuery.error ?? data.error
  const { visible: chromeVisible, poke: revealChrome } = useIdleChrome(
    (!data.display && !error) || dialog !== 'none' || controlsHovered || controlsFocused,
  )
  const controlsVisible = !controlsHidden && chromeVisible

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
      setLookState((current) => clampLook({ ...current, azDeg: brightest.azimuth_deg }))
    }
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

  const observerOptions = useMemo(
    () => catalog ? observerCandidates(catalog).map((option) => ({
      ...option, name: celestialName(option.id, option.name),
    })) : [],
    [catalog, celestialName],
  )

  const selectBody = (id: string) => {
    setBgId(null)
    navigate(`/worlds/${worldName}/sky/${id}${window.location.search}`, { replace: true })
  }
  const deselectBody = () => {
    navigate(`/worlds/${worldName}/sky${window.location.search}`, { replace: true })
  }
  /** Selecting a universe-setting object clears any body selection (and vice
   *  versa via selectBody) — one info panel, two namespaces. */
  const selectBgObject = (id: string) => {
    deselectBody()
    setBgId(id)
  }
  const clearSelection = () => {
    deselectBody()
    setBgId(null)
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

  const display = useMemo(() => data.display && ({
    ...data.display,
    targets: data.display.targets.map((row) => ({ ...row, name: celestialName(row.body_id, row.name) })),
  }), [celestialName, data.display])
  const belowRows = useMemo(() => display?.targets.filter((row) => row.altitude_deg <= 0) ?? [], [display])

  const observerName = observerId && (
    observerOptions.find((option) => option.id === observerId)?.name ?? celestialName(observerId)
  )
  const targetName = bodyId
    ? celestialName(bodyId, data.display?.targets.find((row) => row.body_id === bodyId)?.name
      ?? catalog?.bodies?.find((body) => body.id === bodyId)?.name
      ?? catalog?.stars?.find((star) => star.id === bodyId)?.name)
    : bgId && (background?.stars.find((star) => star.id === bgId)?.name
      ?? background?.deep_sky.find((object) => object.id === bgId)?.name
      ?? culture?.cultures.flatMap((entry) => entry.asterisms).find((asterism) => asterism.id === bgId)?.name
      ?? bgId)
  const safeLook = clampLook(look)
  const helpTarget = { pathname: '/help', hash: '#sky-viewer' }

  // All hooks above; the static-mode guard renders after them (packs pattern).
  if (staticMode) {
    return (
      <section className="mx-auto max-w-lg space-y-3 px-6 py-16">
        <h1 className="text-2xl font-semibold text-gray-100">{t('title.sky')}</h1>
        <p className="text-sm leading-relaxed text-slate-300">{t('staticModeHint')}</p>
        <Link to={helpTarget} className="inline-flex min-h-11 items-center gap-2 text-sm text-neon-cyan hover:underline">
          <AtlasIcon name="help" className="size-4" /> {t('ui.guide')}
        </Link>
      </section>
    )
  }

  const chromeClass = `transition-opacity duration-300 motion-reduce:transition-none ${
    controlsHidden ? 'invisible' : controlsVisible ? 'opacity-100' : 'opacity-0'
  }`
  const chromeHit = controlsVisible ? 'pointer-events-auto' : ''
  const chromeEvents = {
    onPointerEnter: (event: PointerEvent<HTMLElement>) => {
      if (event.pointerType === 'mouse') setControlsHovered(true)
    },
    onPointerLeave: () => setControlsHovered(false),
    onFocus: () => setControlsFocused(true),
    onBlur: (event: FocusEvent<HTMLElement>) => {
      if (!event.currentTarget.contains(event.relatedTarget)) setControlsFocused(false)
    },
  }
  const closeDialog = () => {
    setDialog('none')
    dialogTrigger.current?.focus()
  }

  return (
    <Suspense fallback={<div className="p-6 text-sm text-slate-300">{t('status.loading')}</div>}>
      <main className="fixed inset-0 overflow-hidden bg-[#030308] text-slate-100 [&_:focus-visible]:outline [&_:focus-visible]:outline-2 [&_:focus-visible]:outline-offset-2 [&_:focus-visible]:outline-neon-cyan"
        onKeyDown={(event) => {
          if (event.key === 'Escape' && dialog !== 'none') {
            event.preventDefault()
            closeDialog()
          }
        }}>
        {/* The sky, filling everything */}
        <div ref={skyRef} className="absolute inset-0"
          onPointerMove={controlsHidden ? undefined : revealChrome} onPointerDown={controlsHidden ? undefined : revealChrome}>
          {error ? (
            <div className="flex h-full items-center justify-center px-8">
              <div className="max-w-md text-center text-sm text-red-200" role="alert">
                <p className="font-semibold">{t('status.error')}</p>
                <p className="mt-1 break-words">{error.message}</p>
              </div>
            </div>
          ) : !display || (mode === 'pan' && !size) ? (
            <div className="w-full h-full flex items-center justify-center">
              <div className="text-sm text-slate-300" role="status">{t('status.loading')}</div>
            </div>
          ) : mode === 'pan' ? (
            <SkyPanChart
              result={display}
              catalog={catalog}
              width={size!.width}
              height={size!.height}
              look={look}
              onLookChange={setLook}
              onLookCommit={commitLook}
              grids={grids}
              background={background}
              backgroundOn={backgroundOn}
              culture={culture}
              cultureOn={cultureOn}
              selectedId={bodyId ?? null}
              hoveredId={hoveredId}
              onHover={setHoveredId}
              onSelect={selectBody}
              onBackgroundSelect={clearSelection}
              selectedBgId={bgId}
              onBgSelect={selectBgObject}
            />
          ) : (
            <div className="absolute inset-0 p-4 md:p-8">
              <SkyChart
                result={display}
                catalog={catalog}
                selectedId={bodyId ?? null}
                hoveredId={hoveredId}
                onHover={setHoveredId}
                onSelect={selectBody}
                look={look}
                grids={grids}
                background={background}
                backgroundOn={backgroundOn}
                culture={culture}
                cultureOn={cultureOn}
              />
            </div>
          )}
        </div>

        <div className="pointer-events-none absolute inset-0 grid grid-rows-[auto_minmax(0,1fr)_auto] gap-2 p-3 sm:p-4">
          <header className="flex items-start justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2 rounded-xl border border-space-border bg-space-panel/95 pr-3">
              <Link to={{ pathname: `/worlds/${worldName}`, search: branch ? new URLSearchParams({ branch }).toString() : '' }}
                className={`${iconButton} pointer-events-auto size-11 self-start`} aria-label={t('ui.back')} title={t('ui.back')}>
                <AtlasIcon name="back" />
              </Link>
              <div className="min-w-0 py-2 text-xs leading-relaxed">
                <h1 className="truncate font-semibold text-slate-100" title={observerName ?? undefined}>
                  {observerName ? t('ui.observingFrom', { observer: observerName }) : t('title.sky')}
                </h1>
                <div className="flex flex-wrap items-baseline gap-x-3 text-slate-300">
                  <span className="whitespace-nowrap tabular-nums" title={`${t('observer.lat')}, ${t('observer.lon')}`}>
                    {lat.toFixed(2)}°, {lon.toFixed(2)}°
                  </span>
                  {data.display && <span className="whitespace-nowrap tabular-nums">
                    {referenceEpoch
                      ? t('ui.instantFromEpoch', { epoch: referenceEpoch.label, offset: epochOffset(data.display.at_days) })
                      : t('ui.instant', { days: data.display.at_days.toFixed(2) })}
                  </span>}
                  {targetName && <span className="min-w-0 truncate text-neon-cyan" title={targetName}>
                    {t('ui.target', { name: targetName })}
                  </span>}
                </div>
              </div>
            </div>
            <button type="button" aria-expanded={controlsVisible} aria-controls="sky-controls sky-time-controls"
              className="pointer-events-auto inline-flex min-h-11 shrink-0 items-center gap-2 rounded-lg border border-space-border bg-space-panel/95 px-3 text-xs font-medium text-slate-200 hover:border-neon-cyan/50 hover:text-neon-cyan"
              onClick={() => {
                setControlsHidden(controlsVisible)
                setControlsHovered(false)
                setDialog('none')
                revealChrome()
              }}>
              <AtlasIcon name="menu" className="size-4" />
              {t(controlsVisible ? 'ui.hideControls' : 'ui.showControls')}
            </button>
          </header>

          <div className="relative flex min-h-0 items-start gap-2">
            <div id="sky-controls" className={`${chromeClass} flex max-h-full min-w-0 max-w-full flex-col gap-2`} {...chromeEvents}>
              <div className={`${chromeHit} flex w-fit shrink-0 items-stretch rounded-lg border border-space-border bg-space-panel/95`}>
                {([
                  ['observer', 'globe', t('dialog.observer.title')],
                  ['display', 'layers', t('dialog.display.title')],
                ] as const).map(([key, icon, label]) => (
                  <button key={key} type="button" aria-expanded={dialog === key} aria-controls={`sky-${key}-settings`}
                    onClick={(event) => {
                      dialogTrigger.current = event.currentTarget
                      setDialog(dialog === key ? 'none' : key)
                    }}
                    className={`${iconButton} min-h-11 gap-1.5 px-2.5 text-xs aria-expanded:bg-neon-cyan/10 aria-expanded:text-neon-cyan`}>
                    <AtlasIcon name={icon} className="size-4" /> {label}
                  </button>
                ))}
                <Link to={helpTarget} target="_blank" rel="noreferrer" className={`${iconButton} size-11`} aria-label={t('ui.help')} title={t('ui.help')}>
                  <AtlasIcon name="help" className="size-4" />
                </Link>
              </div>
              <div className={`${chromeHit} flex min-h-0 w-72 max-w-full flex-col empty:hidden`}>
                {dialog === 'observer' && <SkyObserverDialog
                  observerOptions={observerOptions}
                  observerId={observerId}
                  onSelectObserver={(id) => setParam('from', id)}
                  lat={lat}
                  lon={lon}
                  onLat={(value) => Number.isFinite(value) && setParam('lat', String(value))}
                  onLon={(value) => Number.isFinite(value) && setParam('lon', String(value))}
                  worldName={worldName ?? ''}
                  branch={branch}
                  onSelectBranch={(value) => setParam('branch', value)}
                  spinSource={data.display?.spin_source ?? null}
                  solarDayDays={solarDay}
                />}
                {dialog === 'display' && <SkyDisplayDialog
                  mode={mode}
                  onMode={(value) => setParam('mode', value === 'pan' ? null : value)}
                  grids={grids}
                  onGrids={setGrids}
                  backgroundOn={backgroundOn}
                  onBackgroundOn={(on) => setParam('bg', on ? null : '0')}
                  cultureOn={cultureOn}
                  onCultureOn={(on) => setParam('cul', on ? null : '0')}
                  hasCulture={hasCulture}
                  activePanel={activePanel}
                  onSelectPanel={(panel) => {
                    setPanel(panel)
                    if (panel) closeDialog()
                  }}
                />}
              </div>
            </div>

            {display && (bodyId || bgId || activePanel) && (
              <aside className={`${dialog === 'none' ? 'flex' : 'hidden md:flex'} absolute bottom-0 right-0 max-h-[min(65%,calc(100%-3.5rem))] min-h-0 w-full flex-col items-end gap-2 md:static md:max-h-full md:min-w-0 md:w-auto md:flex-1`} aria-label={t('dialog.display.panels')}>
                {(bodyId || bgId) && (
                  <div className={`${panelShell} ${activePanel ? 'hidden md:block' : ''} pointer-events-auto relative w-64 max-w-full`}>
                    <button type="button" onClick={clearSelection} className={`${iconButton} absolute right-1 top-1 size-9`}
                      aria-label={t('ui.closeTarget')} title={t('ui.closeTarget')}>
                      <AtlasIcon name="close" className="size-4" />
                    </button>
                    {bodyId ? <SkyInspector result={display} selectedId={bodyId} /> : (
                      <SkyObjectInspector background={background ?? undefined} cultures={culture} selectedId={bgId} />
                    )}
                  </div>
                )}
                {activePanel && (
                  <div className={`${panelShell} pointer-events-auto w-full max-w-xl`}>
                    <div className="mb-1 flex items-center justify-between gap-2">
                      <h2 className="text-xs font-semibold text-neon-cyan">{t(`panels.${activePanel}`)}</h2>
                      <button type="button" onClick={() => setPanel(null)} className={`${iconButton} size-9`}
                        aria-label={t('ui.closePanel')} title={t('ui.closePanel')}>
                        <AtlasIcon name="close" className="size-4" />
                      </button>
                    </div>
                    {activePanel === 'almanac' ? (
                      <SkyRiseSetTable result={display} selectedId={bodyId ?? null} onSelect={selectBody} />
                    ) : <SkyBelowHorizonList rows={belowRows} selectedId={bodyId ?? null} />}
                  </div>
                )}
              </aside>
            )}
          </div>

          <div id="sky-time-controls" className={`${chromeClass} ${chromeHit} mx-auto w-full max-w-3xl rounded-xl border border-space-border bg-space-panel/95 px-3 py-2 sm:px-4`} {...chromeEvents}>
            {mode === 'pan' && <div className="mb-1.5 flex flex-wrap justify-between gap-x-4 border-b border-space-border pb-1.5 text-xs text-slate-400">
              <span className="tabular-nums">
                {t('chart.azimuth')} {safeLook.azDeg.toFixed(0)}° · {t('chart.altitude')}{' '}
                {safeLook.altDeg >= 0 ? '+' : ''}{safeLook.altDeg.toFixed(0)}° · {t('pan.fov')} {safeLook.fovDeg.toFixed(0)}°
              </span>
              <span className="hidden sm:inline">{t('pan.hint')}</span>
            </div>}
            <SkyTimeControl time={time} solarDayDays={solarDay} referenceEpoch={referenceEpoch} />
          </div>
        </div>

      </main>
    </Suspense>
  )
}
