import { useTranslation } from 'react-i18next'

import type { SkyEphemerisResult } from './types'

export interface SkyRiseSetTableProps {
  result: SkyEphemerisResult
  selectedId: string | null
  onSelect: (bodyId: string) => void
}

export default function SkyRiseSetTable({ result, selectedId, onSelect }: SkyRiseSetTableProps) {
  const { t } = useTranslation('sky')
  if (result.targets.length === 0) return null
  const hasEvents = result.targets.some((row) => row.rise_state !== null)
  return (
    <div className="overflow-x-auto">
      <table className="w-full whitespace-nowrap text-xs [&_td]:px-1 [&_th]:px-1">
        <thead className="text-slate-400">
          <tr className="text-right">
            <th scope="col" className="text-left font-normal">{t('ui.tableBody')}</th>
            <th scope="col" className="font-normal">{t('chart.altitude')}°</th>
            <th scope="col" className="font-normal">{t('chart.azimuth')}°</th>
            <th scope="col" className="font-normal">{t('inspector.magnitude')}</th>
            <th scope="col" className="text-left font-normal">{t('rise.state')}</th>
            <th scope="col" className="font-normal">{t('rise.nextRise')}</th>
            <th scope="col" className="font-normal">{t('rise.nextSet')}</th>
          </tr>
        </thead>
        <tbody className="tabular-nums text-slate-300">
          {result.targets.map((row) => (
            <tr key={row.body_id} onClick={() => onSelect(row.body_id)}
              className={`cursor-pointer text-right hover:bg-space-surface ${row.body_id === selectedId ? 'text-amber-300' : ''}`}>
              <td className="text-left">
                <button type="button" className="min-h-7 rounded text-left hover:underline" aria-current={row.body_id === selectedId || undefined}>
                  {row.name ?? row.body_id}
                </button>
              </td>
              <td>{row.altitude_deg >= 0 ? '+' : ''}{row.altitude_deg.toFixed(1)}</td>
              <td>{row.azimuth_deg.toFixed(0)}</td>
              <td>{row.apparent_magnitude.toFixed(1)}</td>
              <td className="text-left">{row.rise_state !== null ? t(`rise.${row.rise_state}`) : '—'}</td>
              <td>{row.next_rise_days !== null ? `${row.next_rise_days.toFixed(2)}d` : '—'}</td>
              <td>{row.next_set_days !== null ? `${row.next_set_days.toFixed(2)}d` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!hasEvents && <p className="mt-2 text-xs text-slate-400">{t('chart.noRiseInfo')}</p>}
    </div>
  )
}
