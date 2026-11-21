import { useId, useRef, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  encodeRegionWindow,
  readRegionWindow, REGION_WINDOW_PARAM, type RegionWindow,
} from '../../viewers/map/regionWindow'
import type { LonLat } from '../../viewers/map/utils/mapCoords'
import type { GlobeScale } from '../../viewers/map/utils/globeScale'
import MapHelpLink from './MapHelpLink'
import type { MapMode } from '../../viewers/map/useTemperatureTrialPreview'

const buttonClass = 'atlas-tool-button'
const inputClass = 'w-24 rounded border border-space-border bg-space-surface px-2 py-1 text-gray-200'

interface RegionWindowPanelProps {
  world: string
  planet: string
  branch: string | null
  radiusKm: number
  selectedPoint?: LonLat | null
  onMoveToRegion: () => void
  onRegionScale?: (scale: GlobeScale) => void
  scaleAltitudeKm?: number
  scaleDetail?: 'ready' | 'loading' | 'failed' | 'missing'
  modeControl?: { mode: MapMode; onChange: (mode: MapMode) => void }
}

export default function RegionWindowPanel({
  world, planet, branch, radiusKm, selectedPoint, onMoveToRegion, onRegionScale, scaleAltitudeKm, scaleDetail, modeControl,
}: RegionWindowPanelProps) {
  const { t } = useTranslation('map')
  const [search, setSearch] = useSearchParams()
  const location = useLocation()
  const rawWindow = search.get(REGION_WINDOW_PARAM)
  const window = readRegionWindow(rawWindow, radiusKm)
  const [expanded, setExpanded] = useState(false)
  const formId = useId()
  const expandButton = useRef<HTMLButtonElement>(null)
  const regionParams = new URLSearchParams({ world, planet, radius: String(radiusKm),
    view: location.pathname.split('/')[3] === 'globe' ? 'globe' : 'map' })
  if (branch) regionParams.set('branch', branch)
  if (window) regionParams.set(REGION_WINDOW_PARAM, encodeRegionWindow(window))

  const writeWindow = (nextWindow: string | null) => setSearch((previous) => {
    const next = new URLSearchParams(previous)
    if (nextWindow) next.set(REGION_WINDOW_PARAM, nextWindow)
    else next.delete(REGION_WINDOW_PARAM)
    return next
  }, { replace: true })
  const move = (nextWindow: RegionWindow) => {
    const encoded = encodeRegionWindow(nextWindow)
    if (encoded !== rawWindow) writeWindow(encoded)
    onMoveToRegion()
  }

  return (
    <section className="relative z-20 shrink-0 border-b border-space-border bg-space-panel px-2 py-1 text-xs md:px-4 md:py-2">
      <div className="flex flex-wrap items-center gap-1.5 md:gap-2">
        {modeControl && <label className="inline-flex shrink-0 items-center gap-1.5 text-gray-400">
          {t('workbench.mode')}
          <select value={modeControl.mode}
            onChange={event => modeControl.onChange(event.target.value === 'trial' ? 'trial' : 'official')}
            className="min-h-9 rounded border border-space-border bg-space-bg px-2 text-xs text-gray-100 focus-visible:outline focus-visible:outline-neon-cyan">
            <option value="official">{t('workbench.official')}</option>
            <option value="trial">{t('workbench.trial')}</option>
          </select>
        </label>}
        <button ref={expandButton} type="button" className={buttonClass} aria-expanded={expanded} aria-controls={expanded ? formId : undefined}
          title={t('regionWindow.hint.toggle')}
          onClick={() => setExpanded((open) => !open)}>{t('regionWindow.title')}</button>
        {window && <span className="text-gray-300" title={t('regionWindow.summary', { ...window })}>
          <span className="font-mono tabular-nums md:hidden" aria-hidden="true">{window.spanKm} km</span>
          <span className="sr-only md:not-sr-only">{t('regionWindow.summary', { ...window })}</span>
        </span>}
        {window && <Link className={`${buttonClass} font-semibold !text-neon-cyan`} to={`/packs?${regionParams}`} title={t('regionWindow.hint.open')}
          state={{ regionReturn: `${location.pathname}${location.search}` }}>{t('regionWindow.open')}</Link>}
        {window && onRegionScale && <div className="hidden flex-wrap items-center gap-2 md:flex">
          <button type="button" className={buttonClass} onClick={() => onRegionScale('region')}>
            {t('regionWindow.zoomToRegion')}
          </button>
          <button type="button" className={buttonClass} onClick={() => onRegionScale('globe')}>
            {t('regionWindow.zoomToGlobe')}
          </button>
          {scaleAltitudeKm !== undefined && <span className="text-gray-400">
            {t('regionWindow.scaleAltitude', { km: scaleAltitudeKm.toFixed(1) })}
          </span>}
          {scaleDetail && <span role="status" className="text-gray-400">{t(`regionWindow.scaleDetail.${scaleDetail}`)}</span>}
        </div>}
        <div className="ml-auto">
          <MapHelpLink section="region-selection" label={t('regionWindow.help')} />
        </div>
      </div>
      {expanded && (
        <div id={formId} className="absolute inset-x-0 top-full max-h-[55dvh] space-y-2 overflow-y-auto border-b border-space-border bg-space-panel p-3 shadow-lg md:static md:mt-2 md:max-h-[40dvh] md:border-0 md:p-0 md:shadow-none"
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return
            event.preventDefault()
            setExpanded(false)
            expandButton.current?.focus()
          }}>
          {window && onRegionScale && <div className="flex flex-wrap items-center gap-2 md:hidden">
            <button type="button" className={buttonClass} onClick={() => { onRegionScale('region'); setExpanded(false); expandButton.current?.focus() }}>
              {t('regionWindow.zoomToRegion')}
            </button>
            <button type="button" className={buttonClass} onClick={() => { onRegionScale('globe'); setExpanded(false); expandButton.current?.focus() }}>
              {t('regionWindow.zoomToGlobe')}
            </button>
            {scaleAltitudeKm !== undefined && <span className="text-gray-400">{t('regionWindow.scaleAltitude', { km: scaleAltitudeKm.toFixed(1) })}</span>}
            {scaleDetail && <span role="status" className="text-gray-400">{t(`regionWindow.scaleDetail.${scaleDetail}`)}</span>}
          </div>}
          <RegionWindowForm key={rawWindow ?? ''} initial={window} radiusKm={radiusKm}
            selectedPoint={selectedPoint} onMove={move} />
          {rawWindow && <button type="button" className={buttonClass} title={t('regionWindow.hint.clear')}
            onClick={() => writeWindow(null)}>
            {t('regionWindow.clear')}
          </button>}
        </div>
      )}
    </section>
  )
}

function RegionWindowForm({ initial, radiusKm, selectedPoint, onMove }: {
  initial: RegionWindow | null
  radiusKm: number
  selectedPoint?: LonLat | null
  onMove: (window: RegionWindow) => void
}) {
  const { t } = useTranslation('map')
  const [lat, setLat] = useState(initial?.lat.toString() ?? '')
  const [lon, setLon] = useState(initial?.lon.toString() ?? '')
  const [spanKm, setSpanKm] = useState(initial?.spanKm.toString() ?? '500')
  const [invalid, setInvalid] = useState(false)

  return (
    <form noValidate className="flex flex-wrap items-end gap-2" onSubmit={(event) => {
      event.preventDefault()
      const window = readRegionWindow(`${lat},${lon},${spanKm}`, radiusKm)
      setInvalid(window === null)
      if (window) onMove(window)
    }}>
      <label className="flex flex-col gap-1 text-gray-400">
        {t('regionWindow.latitude')}
        <input className={inputClass} type="number" step="any" value={lat} title={t('regionWindow.hint.latitude')}
          onChange={(event) => setLat(event.target.value)} />
      </label>
      <label className="flex flex-col gap-1 text-gray-400">
        {t('regionWindow.longitude')}
        <input className={inputClass} type="number" step="any" value={lon} title={t('regionWindow.hint.longitude')}
          onChange={(event) => setLon(event.target.value)} />
      </label>
      <label className="flex flex-col gap-1 text-gray-400">
        {t('regionWindow.span')}
        <input className={inputClass} type="number" step="any" value={spanKm} title={t('regionWindow.hint.span')}
          onChange={(event) => setSpanKm(event.target.value)} />
      </label>
      <span title={t(selectedPoint ? 'regionWindow.hint.usePoint' : 'regionWindow.hint.needsPoint')}>
        <button type="button" className={`${buttonClass} disabled:pointer-events-none disabled:opacity-50`}
          disabled={!selectedPoint} onClick={() => {
            if (!selectedPoint) return
            setLat(String(selectedPoint.lat))
            setLon(String(selectedPoint.lon))
            setInvalid(false)
          }}>{t('regionWindow.usePoint')}</button>
      </span>
      <button type="submit" className={buttonClass} title={t('regionWindow.hint.move')}>{t('regionWindow.apply')}</button>
      {invalid && <p role="alert" className="text-red-300">
        {t('regionWindow.invalid', { limit: Math.floor(Math.PI * radiusKm) })}
      </p>}
    </form>
  )
}
