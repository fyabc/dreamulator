import { useState, type ReactNode, type Ref } from 'react'
import { useTranslation } from 'react-i18next'
import AtlasIcon, { type AtlasIconName } from '../AtlasIcon'

export function MapInspectorPane({ children, footer, panelRef, labelledBy, className = '' }: {
  children: ReactNode; footer?: ReactNode; panelRef?: Ref<HTMLElement>; labelledBy?: string; className?: string
}) {
  return <aside ref={panelRef} aria-label={labelledBy} className={`min-h-0 flex-col ${className}`}>
    <div className="min-h-0 flex-1 overflow-y-auto p-3">{children}</div>
    {footer}
  </aside>
}

export const inspectorDesktopPane = 'w-52 shrink-0 border-l border-space-border bg-space-panel/50'

export function MapInspectorBody({ details, stats, detailsLabel, onClose }: {
  details: ReactNode; stats?: ReactNode; detailsLabel?: string; onClose?: () => void
}) {
  const { t } = useTranslation('map')
  const [view, setView] = useState<'cell' | 'stats'>('cell')
  const active = stats == null ? 'cell' : view
  return <div className="space-y-2">
    <div className="flex items-center gap-1">
      <div className="flex flex-1 rounded-md bg-gray-800/60 p-0.5">
        {stats == null ? <h2 className="flex-1 rounded bg-neon-cyan/20 py-1 text-center text-xs text-neon-cyan">
          {detailsLabel ?? t('inspector.cellTab')}
        </h2> : (['cell', 'stats'] as const).map(tab => <button key={tab} type="button"
          onClick={() => setView(tab)} aria-pressed={active === tab}
          className={`flex-1 rounded py-1 text-xs transition-colors ${active === tab ? 'bg-neon-cyan/20 text-neon-cyan' : 'text-gray-500 hover:text-gray-300'}`}>
          {tab === 'cell' ? (detailsLabel ?? t('inspector.cellTab')) : t('inspector.statsTab')}
        </button>)}
      </div>
      {onClose && <button type="button" aria-label={t('packs.entry.closeProbe')} title={t('packs.entry.closeProbe')}
        onClick={onClose} className="flex size-11 items-center justify-center rounded text-gray-300 hover:bg-space-surface lg:size-7">
        <AtlasIcon name="close" className="size-4" />
      </button>}
    </div>
    {active === 'stats' ? stats : details}
  </div>
}

export function FieldGroup({ icon, label, defaultOpen = false, children }: {
  icon: AtlasIconName; label: string; defaultOpen?: boolean; children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return <div>
    <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open}
      className="flex w-full select-none items-center gap-1.5 py-0.5 text-xs text-gray-300 hover:text-white">
      <svg aria-hidden="true" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
        className={`transition-transform duration-150 ${open ? 'rotate-90' : ''}`}>
        <polyline points="9 6 15 12 9 18" />
      </svg>
      <AtlasIcon name={icon} className="size-3.5 text-gray-400" />
      <span className="font-medium">{label}</span>
    </button>
    {open && <dl className="ml-4 mt-1 space-y-1 text-xs">{children}</dl>}
  </div>
}

export function FieldValue({ label, children }: { label: string; children: ReactNode }) {
  return <div className="flex justify-between gap-2">
    <dt className="text-gray-500">{label}</dt>
    <dd className="text-right font-mono">{children}</dd>
  </div>
}

export function CoordinateFields({ point, digits = 2 }: { point: { lon: number; lat: number }; digits?: number }) {
  const { t } = useTranslation('map')
  return <>
    <FieldValue label={t('inspector.longitude')}>{point.lon.toFixed(digits)}°</FieldValue>
    <FieldValue label={t('inspector.latitude')}>{point.lat.toFixed(digits)}°</FieldValue>
  </>
}
