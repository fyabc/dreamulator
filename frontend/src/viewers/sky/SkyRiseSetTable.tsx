/** SkyRiseSetTable — the collapsible all-bodies almanac under the chart.
 *  Fast-path rows show a hint instead of fake emptiness.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { SkyEphemerisResult } from './types'

export interface SkyRiseSetTableProps {
  result: SkyEphemerisResult | undefined
  selectedId: string | null
  onSelect: (bodyId: string) => void
  /** Start expanded (the floating panel context). */
  defaultOpen?: boolean
}

export default function SkyRiseSetTable({ result, selectedId, onSelect, defaultOpen = false }: SkyRiseSetTableProps) {
  const { t } = useTranslation('sky')
  const [open, setOpen] = useState(defaultOpen)
  if (!result || result.targets.length === 0) return null
  const hasEvents = result.targets.some((r) => r.rise_state !== null)
  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="text-[11px] text-gray-400 hover:text-neon-cyan transition-colors"
      >
        {open ? '▾' : '▸'} {t('rise.tableTitle')}
      </button>
      {open && (
        <table className="w-full mt-1 text-[10px]">
          <thead>
            <tr className="text-gray-500 text-left">
              <th className="font-normal py-0.5">{t('observer.label')}</th>
              <th className="font-normal py-0.5 text-right">{t('chart.altitude')}°</th>
              <th className="font-normal py-0.5 text-right">{t('chart.azimuth')}°</th>
              <th className="font-normal py-0.5 text-right">{t('inspector.magnitude')}</th>
              <th className="font-normal py-0.5">{t('rise.state')}</th>
              <th className="font-normal py-0.5 text-right">{t('rise.nextRise')}</th>
              <th className="font-normal py-0.5 text-right">{t('rise.nextSet')}</th>
            </tr>
          </thead>
          <tbody className="font-mono tabular-nums text-gray-400">
            {result.targets.map((row) => (
              <tr
                key={row.body_id}
                onClick={() => onSelect(row.body_id)}
                className={`cursor-pointer hover:text-gray-200 ${row.body_id === selectedId ? 'text-amber-300' : ''}`}
              >
                <td className="py-0.5 font-sans">{row.name ?? row.body_id}</td>
                <td className="py-0.5 text-right">{row.altitude_deg >= 0 ? '+' : ''}{row.altitude_deg.toFixed(1)}</td>
                <td className="py-0.5 text-right">{row.azimuth_deg.toFixed(0)}</td>
                <td className="py-0.5 text-right">{row.apparent_magnitude.toFixed(1)}</td>
                <td className="py-0.5 font-sans">
                  {row.rise_state !== null ? t(`rise.${row.rise_state}`) : `— ${t('chart.noRiseInfo')}`}
                </td>
                <td className="py-0.5 text-right">{row.next_rise_days !== null ? `${row.next_rise_days.toFixed(2)}d` : '—'}</td>
                <td className="py-0.5 text-right">{row.next_set_days !== null ? `${row.next_set_days.toFixed(2)}d` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!hasEvents && (
        <div className="text-[10px] text-gray-600 mt-1">{t('chart.noRiseInfo')}</div>
      )}
    </div>
  )
}
