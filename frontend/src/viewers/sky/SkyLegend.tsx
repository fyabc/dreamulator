/** SkyLegend — the marker-language legend.  Overlay variant floats inside the
 *  chart (MapLegend pattern); inline variant sits in a dialog/panel. */

import { useTranslation } from 'react-i18next'

import { BODY_FILL, LIT_FILL } from './bodyColor'

export interface SkyLegendProps {
  /** Floating chart overlay (default) or flow content for a dialog. */
  variant?: 'overlay' | 'inline'
}

export default function SkyLegend({ variant = 'overlay' }: SkyLegendProps) {
  const { t } = useTranslation('sky')
  const rows: Array<[string, string]> = [
    [t('legend.size'), BODY_FILL],
    [t('legend.starColor'), '#ffd9a0'],
    [t('legend.phase'), LIT_FILL],
  ]
  const content = (
    <>
      <div className={variant === 'inline' ? 'text-[11px] text-gray-300 mb-1' : 'text-[11px] text-gray-300'}>
        {t('legend.title')}
      </div>
      {rows.map(([label, color]) => (
        <div key={label} className="flex items-center gap-1.5 text-[10px] text-gray-400">
          <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: color }} />
          {label}
        </div>
      ))}
      <div className="text-[10px] text-gray-500">{t('legend.dim')}</div>
    </>
  )
  if (variant === 'inline') return <div className="space-y-0.5">{content}</div>
  return (
    <div className="absolute bottom-2 left-2 border border-space-border bg-space-panel/80 backdrop-blur-sm pointer-events-none rounded p-2 space-y-0.5">
      {content}
    </div>
  )
}
