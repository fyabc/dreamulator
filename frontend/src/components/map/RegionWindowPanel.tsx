import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import {
  availableRegionPacks, encodeRegionWindow, matchingRegionPacks, packRegionWindow,
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
}

export default function RegionWindowPanel({ world, planet, branch, radiusKm, selectedPoint }: RegionWindowPanelProps) {
  const { t } = useTranslation('map')
  const [search, setSearch] = useSearchParams()
  const location = useLocation()
  const rawWindow = search.get(REGION_WINDOW_PARAM)
  const window = readRegionWindow(rawWindow, radiusKm)
  const [expanded, setExpanded] = useState(window !== null)
  const staticMode = isStaticMode()
  const packs = useQuery({ queryKey: ['packs'], queryFn: api.listPacks, enabled: expanded && !staticMode, retry: false })
  const available = availableRegionPacks(packs.data ?? [], { world, planet, branch }, radiusKm)
  const matching = window ? matchingRegionPacks(available, window, radiusKm) : []

  const save = (nextWindow: RegionWindow | null) => setSearch((previous) => {
    const next = new URLSearchParams(previous)
    if (nextWindow) next.set(REGION_WINDOW_PARAM, encodeRegionWindow(nextWindow))
    else next.delete(REGION_WINDOW_PARAM)
    return next
  }, { replace: true })

  return (
    <section className="shrink-0 border-b border-space-border bg-space-panel px-3 py-2 text-xs sm:px-4">
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={buttonClass} aria-expanded={expanded}
          title={t('regionWindow.hint.toggle')}
          onClick={() => setExpanded((open) => !open)}>{t('regionWindow.title')}</button>
        {window && <span className="text-neon-cyan">{t('regionWindow.summary', { ...window })}</span>}
        <div className="ml-auto">
          <MapHelpLink section="region-selection" label={t('regionWindow.help')} />
        </div>
      </div>
      {expanded && (
        <div className="mt-2 space-y-2">
          <RegionWindowForm key={rawWindow ?? ''} initial={window} radiusKm={radiusKm}
            selectedPoint={selectedPoint} onSave={save} />
          {rawWindow && <button type="button" className={buttonClass} title={t('regionWindow.hint.clear')}
            onClick={() => save(null)}>
            {t('regionWindow.clear')}
          </button>}
          {staticMode ? <p className="text-gray-400">{t('regionWindow.staticHint')}</p> : (
            <div className="flex flex-wrap items-center gap-2 text-gray-400">
              {packs.isPending && <p role="status">{t('status.loading')}</p>}
              {packs.isError && <p role="status">{t('regionWindow.packListFailed')}</p>}
              {available.length > 0 && (
                <label className="flex flex-wrap items-center gap-2">
                  {t('regionWindow.existing')}
                  <select className={buttonClass} value="" title={t('regionWindow.hint.existing')} onChange={(event) => {
                    const pack = available.find(({ name }) => name === event.target.value)
                    if (pack) save(packRegionWindow(pack, radiusKm))
                  }}>
                    <option value="">{t('regionWindow.chooseExisting')}</option>
                    {available.map((pack) => <option key={pack.name} value={pack.name}>{pack.name}</option>)}
                  </select>
                </label>
              )}
              {packs.isSuccess && window && matching.length === 0 && <p>{t('regionWindow.noExactPack')}</p>}
              {matching.map(({ name }) => (
                <Link key={name} className={buttonClass} to={`/packs?${new URLSearchParams({ pack: name })}`}
                  title={t('regionWindow.hint.open')}
                  state={{ regionReturn: `${location.pathname}${location.search}` }}>
                  {t('regionWindow.openPack', { name })}
                </Link>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

function RegionWindowForm({ initial, radiusKm, selectedPoint, onSave }: {
  initial: RegionWindow | null
  radiusKm: number
  selectedPoint?: LonLat | null
  onSave: (window: RegionWindow) => void
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
      if (window) onSave(window)
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
      <button type="submit" className={buttonClass} title={t('regionWindow.hint.save')}>{t('regionWindow.apply')}</button>
      {invalid && <p role="alert" className="text-red-300">
        {t('regionWindow.invalid', { limit: Math.floor(Math.PI * radiusKm) })}
      </p>}
    </form>
  )
}
