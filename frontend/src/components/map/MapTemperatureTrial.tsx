import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { isStaticMode } from '../../api/mode'
import type { ClimateTrialResult } from '../../api/climateTrials'
import type { TemperaturePreview } from '../../playground/temperaturePreview'

const TemperatureLab = lazy(() => import('../../playground/TemperatureLab'))
const EbmClimateLab = lazy(() => import('../../playground/EbmClimateLab'))
const SavedClimateLab = lazy(() => import('../../playground/SavedClimateLab'))
export const trialPanelId = 'map-climate-trial'
export const trialButtonId = 'map-climate-trial-button'

export function MapTemperatureTrial({ open, onClose, search, onPreview, onResult, onShow }: {
  open: boolean
  onClose: () => void
  search: URLSearchParams
  onPreview: (preview: TemperaturePreview | null) => void
  onResult: (result: ClimateTrialResult) => void
  onShow: () => void
}) {
  const { t } = useTranslation('playground')
  const [previewMode, setPreviewMode] = useState(false)
  const saved = !search.has('draft') && search.has('climateResult')
  const browser = isStaticMode() && !search.has('draft') && !saved
  const preview = search.has('draft') || (browser && previewMode)
  const closeButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (open) closeButton.current?.focus({ preventScroll: true })
  }, [open])

  return (
    <section id={trialPanelId} hidden={!open} aria-labelledby={`${trialPanelId}-title`}
      className={`${open ? 'flex' : 'hidden'} absolute inset-x-0 bottom-0 z-[35] max-h-[min(100%,48dvh)] flex-col rounded-t-lg border border-space-border bg-space-panel shadow-xl lg:inset-y-0 lg:left-auto lg:right-0 lg:w-80 lg:max-h-none lg:rounded-none`}
      onKeyDown={event => {
        if (event.key !== 'Escape' || event.defaultPrevented) return
        event.preventDefault()
        event.stopPropagation()
        onClose()
      }}>
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-space-border px-3 py-1">
        <h2 id={`${trialPanelId}-title`} className="text-sm font-semibold text-gray-100">{t(preview ? 'ebm.previewTitle' : saved ? 'ebm.saved.title' : 'ebm.title')}</h2>
        <button ref={closeButton} type="button" onClick={onClose} className="atlas-tool-button text-xs">{t('trial.collapse')}</button>
      </header>
      <div className="min-h-0 overflow-y-auto overscroll-contain px-3 pb-3 pt-2">
        <Suspense fallback={<p role="status" className="text-xs text-gray-400">{t('ebm.readingInputs')}</p>}>
          {preview ? <>
            {browser && <button type="button" onClick={() => setPreviewMode(false)} className="atlas-tool-button mb-2 min-h-9 text-xs">
              {t('ebm.browser.useEbm')}
            </button>}
            <TemperatureLab search={search} map={{ onPreview, onShowPreview: onShow }} />
          </>
            : saved ? <SavedClimateLab search={search} onResult={onResult} onShow={onShow} />
            : <EbmClimateLab search={search} open={open} onResult={onResult} onShow={onShow}
                onPreviewMode={browser ? () => setPreviewMode(true) : undefined} />}
        </Suspense>
      </div>
    </section>
  )
}
