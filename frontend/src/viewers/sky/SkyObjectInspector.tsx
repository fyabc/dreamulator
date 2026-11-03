/** SkyObjectInspector — the selected background object's fields (an authored
 *  star or a deep-sky sprite from the universe setting; system bodies go to
 *  SkyInspector).  Wandering objects are invisible and never selectable.
 */

import { useTranslation } from 'react-i18next'

import type { SkyBackground } from './types'

export interface SkyObjectInspectorProps {
  background: SkyBackground | undefined
  selectedId: string | null
}

export default function SkyObjectInspector({ background, selectedId }: SkyObjectInspectorProps) {
  const { t } = useTranslation('sky')
  if (!background || !selectedId) {
    return <div className="text-[11px] text-gray-500 italic">{t('inspector.none')}</div>
  }
  const star = background.stars.find((s) => s.id === selectedId && s.source === 'authored')
  const dso = star ? undefined : background.deep_sky.find((d) => d.id === selectedId)
  if (!star && !dso) {
    return <div className="text-[11px] text-gray-500 italic">{t('inspector.none')}</div>
  }

  const title = (star?.name ?? dso?.name ?? selectedId) + (star ? ' · ★' : '')
  const rows: Array<[string, string]> = []
  if (star) {
    rows.push([t('objectInspector.magnitude'), star.magnitude.toFixed(2)])
    rows.push([t('objectInspector.temperature'), `${Math.round(star.temperature_k)} K`])
    if (star.variability) {
      rows.push([
        t('objectInspector.variability'),
        t(`objectInspector.varTypes.${star.variability.type}`, star.variability.type),
      ])
      if (star.variability.magnitude_range) {
        const [faint, bright] = star.variability.magnitude_range
        rows.push([
          t('objectInspector.variableRange'),
          `${bright.toFixed(1)} … ${faint.toFixed(1)}`,
        ])
      }
      rows.push([
        t('objectInspector.variablePeriod'),
        star.variability.period_days !== null
          ? t('objectInspector.periodDays', { d: star.variability.period_days })
          : t('objectInspector.irregular'),
      ])
    }
  } else if (dso) {
    rows.push([t('objectInspector.type'), t(`objectInspector.dsoTypes.${dso.type}`)])
    rows.push([t('objectInspector.angularSize'), `${dso.angular_size_deg.toFixed(1)}°`])
    rows.push([t('objectInspector.magnitude'), dso.magnitude.toFixed(1)])
  }

  return (
    <div className="text-[12px] leading-relaxed">
      <div className="text-space-accent text-[13px] font-medium mb-1.5 break-words">{title}</div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-gray-500">{k}</dt>
            <dd className="text-gray-200 text-right">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
