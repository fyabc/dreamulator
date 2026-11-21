import { lazy, Suspense, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { TEMPERATURE_GRADIENT, type TemperaturePreview } from '../../playground/temperaturePreview'

const TemperatureLab = lazy(() => import('../../playground/TemperatureLab'))
export const trialPanelId = 'map-climate-trial'
export const trialButtonId = 'map-climate-trial-button'

export function MapTemperatureTrial({ open, onClose, search, onPreview, onShow, showing }: {
  open: boolean
  onClose: () => void
  search: URLSearchParams
  onPreview: (preview: TemperaturePreview | null) => void
  onShow: () => void
  showing: boolean
}) {
  const { t } = useTranslation('playground')
  const closeButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (open) closeButton.current?.focus({ preventScroll: true })
  }, [open])

  return (
    <section id={trialPanelId} hidden={!open} aria-labelledby={`${trialPanelId}-title`}
      className={`${open ? 'flex' : 'hidden'} absolute inset-x-0 bottom-0 z-[25] max-h-[min(100%,48dvh)] flex-col rounded-t-lg border border-space-border bg-space-panel shadow-xl md:inset-y-0 md:left-auto md:w-72 md:max-h-none md:rounded-none`}
      onKeyDown={event => {
        if (event.key !== 'Escape' || event.defaultPrevented) return
        event.preventDefault()
        event.stopPropagation()
        onClose()
      }}>
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-space-border px-3 py-1">
        <h2 id={`${trialPanelId}-title`} className="text-sm font-semibold text-gray-100">{t('trial.title')}</h2>
        <button ref={closeButton} type="button" onClick={onClose} className="atlas-tool-button text-xs">{t('trial.collapse')}</button>
      </header>
      <div className="min-h-0 overflow-y-auto overscroll-contain px-3 pb-3 pt-2">
        <Suspense fallback={<p role="status" className="text-xs text-gray-400">{t('action.loadingInput')}</p>}>
          <TemperatureLab search={search} map={{ onPreview, onShowPreview: onShow, showing }} />
        </Suspense>
      </div>
    </section>
  )
}

export function MapTemperatureLegend({ preview, onRestore }: { preview: TemperaturePreview; onRestore: () => void }) {
  const { t } = useTranslation('playground')
  return (
    <div className="absolute left-2 top-2 z-20 max-w-[calc(100%_-_1rem)] rounded border border-space-border bg-space-panel px-2.5 py-1.5 shadow-md">
      <div className="flex flex-wrap items-center justify-between gap-x-3 text-xs">
        <p role="status" className="font-medium text-amber-200">{t('trial.previewLabel', { period: preview.label })}{preview.stale ? ` · ${t('trial.stalePreview')}` : ''}</p>
        <button type="button" onClick={onRestore} className="min-h-9 text-neon-cyan hover:underline">{t('trial.restoreLayers')}</button>
      </div>
      <div className="flex items-center gap-2 text-[10px] text-gray-300">
        <span>−40 °C</span><div className="h-1.5 flex-1 rounded" style={{ background: TEMPERATURE_GRADIENT }} /><span>+40 °C</span>
      </div>
    </div>
  )
}
