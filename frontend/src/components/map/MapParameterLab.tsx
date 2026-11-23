import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import ParameterLab from './ParameterLab'

export const parameterPanelId = 'map-parameter-lab'
export const parameterButtonId = 'map-parameter-lab-button'

export function MapParameterLab({ open, onClose, world, planet, branch, openBuild }: {
  open: boolean
  onClose: () => void
  world?: string
  planet?: string
  branch: string | null
  openBuild?: () => void
}) {
  const { t } = useTranslation('map')
  const closeButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (open) closeButton.current?.focus({ preventScroll: true })
  }, [open])

  if (!world || !planet) return null
  return (
    <section id={parameterPanelId} hidden={!open} aria-labelledby={`${parameterPanelId}-title`}
      className={`${open ? 'flex' : 'hidden'} absolute inset-x-0 bottom-0 z-[35] max-h-[min(100%,60dvh)] flex-col rounded-t-lg border border-space-border bg-space-panel shadow-xl lg:inset-y-0 lg:left-auto lg:right-0 lg:w-80 lg:max-h-none lg:rounded-none`}
      onKeyDown={event => {
        if (event.key !== 'Escape' || event.defaultPrevented) return
        event.preventDefault()
        event.stopPropagation()
        onClose()
      }}>
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-space-border px-3 py-1">
        <h2 id={`${parameterPanelId}-title`} className="text-sm font-semibold text-gray-100">{t('parameterLab.title')}</h2>
        <button ref={closeButton} type="button" onClick={onClose} className="atlas-tool-button text-xs">{t('parameterLab.close', { defaultValue: '收起' })}</button>
      </header>
      <div className="min-h-0 overflow-y-auto overscroll-contain px-3 pb-3 pt-2">
        <ParameterLab world={world} planet={planet} branch={branch} openBuild={openBuild} />
      </div>
    </section>
  )
}
