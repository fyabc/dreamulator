import { useEffect, useRef, useState, type ReactNode, type Ref } from 'react'
import { useTranslation } from 'react-i18next'
import AtlasIcon from '../../components/AtlasIcon'
import { inspectorDesktopPane, MapInspectorBody, MapInspectorPane } from '../../components/map/MapInspectorFields'
import { MapLayerDrawer, MapWorkbenchToolbar } from '../../components/map/MapWorkbenchToolbar'

interface Props {
  children: ReactNode
  backTo: string
  backLabel: string
  backRef?: Ref<HTMLAnchorElement>
  subtitle?: string
  layers?: ReactNode
  tools?: ReactNode
  sourceControl?: ReactNode
  regionTools?: ReactNode
  status?: ReactNode
  inspector?: ReactNode
  onClearPoint?: () => void
}

const toolPanelId = 'region-work-panel'
const toolButtonId = 'region-work-button'

export default function RegionMapWorkspace({ children, backTo, backLabel, backRef, subtitle, layers, tools, sourceControl, regionTools, status, inspector, onClearPoint }: Props) {
  const { t } = useTranslation('map')
  const [layersOpen, setLayersOpen] = useState(false)
  const [toolsOpen, setToolsOpen] = useState(false)
  const closeButton = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (toolsOpen) closeButton.current?.focus() }, [toolsOpen])
  const closeTools = () => {
    setToolsOpen(false)
    document.getElementById(toolButtonId)?.focus()
  }
  return (
    <div className="atlas-workbench flex flex-col">
      <MapWorkbenchToolbar view="region" title={t('packs.pickPrompt')} subtitle={subtitle}
        backTo={backTo} backLabel={backLabel} backRef={backRef} layersOpen={layersOpen}
        regionControls={sourceControl}
        onToggleLayers={layers ? () => { setToolsOpen(false); setLayersOpen(open => !open) } : undefined}
        regionPanel={regionTools ? { id: toolPanelId, buttonId: toolButtonId, open: toolsOpen,
          onToggle: () => { setLayersOpen(false); setToolsOpen(open => !open) } } : undefined}>
        {tools}
      </MapWorkbenchToolbar>
      <div className="relative isolate flex min-h-0 flex-1">
        {layers && <MapLayerDrawer persistent open={layersOpen} onClose={() => setLayersOpen(false)}>
          {layers}
        </MapLayerDrawer>}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="relative isolate min-h-0 flex-1 overflow-hidden">
            {children}
          </div>
          {status}
        </div>
        {inspector && <MapInspectorPane labelledBy={t('packs.probeTitle')} panelRef={element => { if (element) element.inert = toolsOpen }}
          className={`${onClearPoint && !toolsOpen ? 'max-lg:flex' : 'max-lg:hidden'} ${inspectorDesktopPane} lg:flex
            max-lg:absolute max-lg:inset-x-3 max-lg:bottom-11 max-lg:z-30 max-lg:max-h-[55%] max-lg:w-auto max-lg:rounded max-lg:border max-lg:bg-space-panel`}>
          <MapInspectorBody detailsLabel={t('packs.probeTitle')} details={inspector} onClose={onClearPoint} />
        </MapInspectorPane>}
        {regionTools && <>
          {toolsOpen && <div className="absolute inset-0 z-40 bg-black/45 lg:hidden" onClick={closeTools} />}
          <aside hidden={!toolsOpen} id={toolPanelId} aria-labelledby="region-panel-title"
            onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); closeTools() } }}
            className="absolute inset-y-0 right-0 z-50 w-[24rem] max-w-[92%] overflow-y-auto border-l border-space-border bg-space-panel shadow-xl">
            <div className="sticky top-0 z-10 flex items-center justify-between gap-2 border-b border-space-border bg-space-panel px-4 py-2">
              <h2 id="region-panel-title" className="text-sm font-semibold text-gray-200">{t('packs.entry.tools')}</h2>
              <button ref={closeButton} type="button" aria-label={t('packs.entry.closeTools')} title={t('packs.entry.closeTools')}
                className="flex size-11 items-center justify-center rounded text-gray-300 hover:bg-space-surface lg:size-8" onClick={closeTools}>
                <AtlasIcon name="close" className="size-4" />
              </button>
            </div>
            <div className="space-y-3 p-4 text-xs text-gray-400">{regionTools}</div>
          </aside>
        </>}
      </div>
    </div>
  )
}
