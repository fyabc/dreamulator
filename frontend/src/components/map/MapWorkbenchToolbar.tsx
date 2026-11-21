import { useEffect, useRef, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import AtlasIcon from '../AtlasIcon'
import MapHelpLink from './MapHelpLink'

const layerPanelId = 'map-layer-panel'
const layerButtonId = 'map-layer-button'

export function MapWorkbenchToolbar({ title, view, backTo, switchTo, trialPanel, layersOpen, onToggleLayers, children }: {
  title: string
  view: 'map' | 'globe'
  backTo: string
  switchTo?: string
  trialPanel?: { id: string; buttonId: string; open: boolean; onToggle: () => void }
  layersOpen: boolean
  onToggleLayers?: () => void
  children: ReactNode
}) {
  const { t } = useTranslation('map')
  const tools = useRef<HTMLDetailsElement>(null)
  const toolsButton = useRef<HTMLElement>(null)

  return (
    <header className="relative z-30 grid shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 border-b border-space-border bg-space-panel px-2 py-1.5 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] lg:gap-3 lg:px-4 lg:py-2">
      <div className="flex min-w-0 items-center gap-2">
        <Link to={backTo} className="inline-flex size-11 shrink-0 items-center justify-center rounded text-gray-300 hover:bg-space-surface"
          aria-label={t('action.back')} title={t('action.back')}><AtlasIcon name="back" /></Link>
        <div className="min-w-0">
          <h1 className="truncate text-lg font-semibold text-gray-100" title={title}>{title}</h1>
          <p className="hidden truncate text-xs text-gray-400 lg:block">{t(view === 'map' ? 'title.viewer' : 'title.globe')}</p>
        </div>
      </div>
      {switchTo && (
        <nav aria-label={t('workbench.views')} className="col-start-1 row-start-2 inline-flex w-fit items-center gap-0.5 rounded border border-space-border bg-space-bg p-0.5 lg:col-start-2 lg:row-start-1">
          {(['map', 'globe'] as const).map((item) => {
            const label = t(item === 'map' ? 'workbench.flat' : 'workbench.globe')
            const dimension = item === 'map' ? '2D' : '3D'
            const contents = <>{label} <span className="font-mono text-[10px]">{dimension}</span></>
            return view === item
              ? <span key={item} aria-current="page" className="inline-flex min-h-10 items-center gap-1 rounded bg-space-surface px-2.5 text-sm font-semibold text-neon-cyan lg:min-h-9">{contents}</span>
              : <Link key={item} to={switchTo} className="inline-flex min-h-10 items-center gap-1 rounded px-2.5 text-sm text-gray-300 hover:bg-space-surface lg:min-h-9">{contents}</Link>
          })}
        </nav>
      )}
      <div className="col-start-2 row-start-1 flex items-center justify-end gap-1.5 lg:col-start-3 lg:gap-2">
        {trialPanel && <button id={trialPanel.buttonId} type="button" onClick={trialPanel.onToggle}
          className="atlas-tool-button text-sm aria-expanded:border-neon-cyan/50 aria-expanded:text-neon-cyan"
          aria-label={t('workbench.climateTrial')} title={t('workbench.climateTrial')}
          aria-expanded={trialPanel.open} aria-controls={trialPanel.id}>
          <AtlasIcon name="flask" className="size-4" /> <span className="hidden lg:inline">{t('workbench.climateTrial')}</span>
        </button>}
        {onToggleLayers && <button id={layerButtonId} type="button" aria-expanded={layersOpen} aria-controls={layersOpen ? layerPanelId : undefined}
          className="atlas-tool-button text-sm lg:hidden" onClick={onToggleLayers}>
          <AtlasIcon name="layers" className="size-4" /> {t('workbench.layers')}
        </button>}
        <details ref={tools} className="group relative" onKeyDown={(event) => {
          if (event.key !== 'Escape' || !tools.current?.open || !event.currentTarget.contains(event.target as Node)) return
          event.preventDefault()
          tools.current.open = false
          toolsButton.current?.focus()
        }}>
          <summary ref={toolsButton} className="atlas-tool-button cursor-pointer list-none text-sm"
            aria-label={t('workbench.tools')} title={t('workbench.tools')}>
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" className="size-4 group-open:rotate-180">
              <path d="m6 9 6 6 6-6" />
            </svg>
            <span className="hidden lg:inline">{t('workbench.tools')}</span>
          </summary>
          <div className="absolute right-0 top-full mt-2 flex max-h-[55dvh] w-64 max-w-[calc(100vw-1.5rem)] flex-col gap-2 overflow-y-auto rounded border border-space-border bg-space-panel p-3 shadow-lg">
            {children}
          </div>
        </details>
        <MapHelpLink section={view === 'map' ? 'map-controls' : 'globe-viewer'} label={t('control.helpButton')} />
      </div>
    </header>
  )
}

export function MapBodySelector({ planets, selected, nameOf, onSelect }: {
  planets: string[]; selected: string; nameOf: (id: string) => string; onSelect: (id: string) => void
}) {
  const { t } = useTranslation('map')
  return <label className="block space-y-1 min-w-0">
    <span className="text-[11px] text-gray-500">{t('workbench.body')}</span>
    <select value={selected} onChange={event => onSelect(event.target.value)}
      className="w-full min-w-0 bg-space-bg border border-space-border rounded-lg px-2 py-1 text-xs text-white focus:outline-none focus:border-neon-cyan transition-colors">
      {planets.map(id => <option key={id} value={id}>{nameOf(id)}</option>)}
    </select>
  </label>
}

export function MapLayerDrawer({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  const { t } = useTranslation('map')
  const closeButton = useRef<HTMLButtonElement>(null)
  useEffect(() => { closeButton.current?.focus() }, [])
  const close = () => {
    onClose()
    document.getElementById(layerButtonId)?.focus()
  }

  return (
    <>
      <div className="absolute inset-0 z-40 bg-black/50" onClick={close} />
      <aside id={layerPanelId} aria-label={t('label.layerSettings')}
        onKeyDown={(event) => {
          if (event.key !== 'Escape') return
          event.preventDefault()
          close()
        }} className="absolute inset-y-0 left-0 z-50 w-64 max-w-[85%] space-y-4 overflow-y-auto border-r border-space-border bg-space-panel p-3 shadow-xl">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-gray-200">{t('label.layerSettings')}</h2>
          <button ref={closeButton} type="button" aria-label={t('workbench.closeLayers')} onClick={close}
            className="inline-flex size-11 items-center justify-center rounded text-gray-300 hover:bg-space-surface">
            <AtlasIcon name="close" className="size-4" />
          </button>
        </div>
        {children}
      </aside>
    </>
  )
}
