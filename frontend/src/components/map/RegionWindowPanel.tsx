import { useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  encodeRegionWindow,
  readRegionWindow, REGION_WINDOW_PARAM, type RegionWindow,
} from '../../viewers/map/regionWindow'
import type { LonLat } from '../../viewers/map/utils/mapCoords'
import MapHelpLink from './MapHelpLink'

const buttonClass = 'rounded border border-space-border bg-space-surface px-2 py-1 text-gray-200 hover:border-neon-cyan/50'
const inputClass = 'w-24 rounded border border-space-border bg-space-surface px-2 py-1 text-gray-200'

interface RegionWindowPanelProps {
  world: string
  planet: string
  branch: string | null
  radiusKm: number
  selectedPoint?: LonLat | null
  onMoveToRegion: () => void
}

export default function RegionWindowPanel({ world, planet, branch, radiusKm, selectedPoint, onMoveToRegion }: RegionWindowPanelProps) {
  const { t } = useTranslation('map')
  const [search, setSearch] = useSearchParams()
  const location = useLocation()
  const rawWindow = search.get(REGION_WINDOW_PARAM)
  const window = readRegionWindow(rawWindow, radiusKm)
  const [expanded, setExpanded] = useState(window !== null)
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
    <section className="shrink-0 border-b border-space-border bg-space-panel px-3 py-2 text-xs sm:px-4">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={buttonClass} aria-expanded={expanded}
          title={t('regionWindow.hint.toggle')}
          onClick={() => setExpanded((open) => !open)}>{t('regionWindow.title')}</button>
        {window && <span className="text-neon-cyan">{t('regionWindow.summary', { ...window })}</span>}
        {window && <Link className={buttonClass} to={`/packs?${regionParams}`} title={t('regionWindow.hint.open')}
          state={{ regionReturn: `${location.pathname}${location.search}` }}>{t('regionWindow.open')}</Link>}
        <div className="ml-auto">
          <MapHelpLink section="region-selection" label={t('regionWindow.help')} />
        </div>
      </div>
      {expanded && (
        <div className="mt-2 max-h-[40dvh] space-y-2 overflow-y-auto pr-1">
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
