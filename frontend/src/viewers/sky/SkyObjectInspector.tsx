/** SkyObjectInspector — the selected background object's fields (an authored
 *  star, a deep-sky sprite, or a sky-culture asterism figure; system bodies go
 *  to SkyInspector).  Wandering objects are invisible and never selectable.
 *  Stars also show any culture names layered over the catalogue id.
 */

import { useTranslation } from 'react-i18next'

import type { SkyBackground, SkyCulture, SkyCultureAsterism, SkyCultureEntry } from './types'

export interface SkyObjectInspectorProps {
  background: SkyBackground | undefined
  /** Civilization-layer star lore; null until fetched or when the world has none. */
  cultures?: SkyCulture | null
  selectedId: string | null
}

function findAsterism(
  cultures: SkyCulture | null | undefined,
  selectedId: string,
): { asterism: SkyCultureAsterism; culture: SkyCultureEntry } | null {
  for (const culture of cultures?.cultures ?? []) {
    const asterism = culture.asterisms.find((a) => a.id === selectedId)
    if (asterism) return { asterism, culture }
  }
  return null
}

export default function SkyObjectInspector({
  background,
  cultures = null,
  selectedId,
}: SkyObjectInspectorProps) {
  const { t } = useTranslation('sky')
  if (!selectedId) {
    return <div className="text-[11px] text-gray-500 italic">{t('inspector.none')}</div>
  }

  const hit = findAsterism(cultures, selectedId)
  if (hit) {
    const { asterism, culture } = hit
    // Member list: resolve the figure's vertex ids against the catalogue.
    const members = new Map<string, string>()
    for (const [a, b] of asterism.lines) {
      for (const id of [a, b]) {
        if (members.has(id)) continue
        const star = background?.stars.find((s) => s.id === id && s.source === 'authored')
        const dso = star ? undefined : background?.deep_sky.find((d) => d.id === id)
        members.set(
          id,
          star
            ? `${star.name ?? id} ${star.magnitude.toFixed(1)}ᵐ`
            : dso
              ? `${dso.name ?? id} ${dso.magnitude.toFixed(1)}ᵐ`
              : id,
        )
      }
    }
    return (
      <div className="text-[12px] leading-relaxed">
        <div className="text-space-accent text-[13px] font-medium mb-1.5 break-words">
          {asterism.name} · {t('objectInspector.asterism')}
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <div className="contents">
            <dt className="text-gray-500">{t('objectInspector.culture')}</dt>
            <dd className="text-gray-200 text-right">{culture.name}</dd>
          </div>
          <div className="contents">
            <dt className="text-gray-500">{t('objectInspector.members')}</dt>
            <dd className="text-gray-200 text-right">{[...members.values()].join(' · ')}</dd>
          </div>
        </dl>
        {asterism.meaning && (
          <p className="mt-2 text-[11px] text-gray-300 leading-relaxed">{asterism.meaning}</p>
        )}
      </div>
    )
  }

  if (!background) {
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
    // Culture names layered over the catalogue id (one row per culture).
    for (const culture of cultures?.cultures ?? []) {
      const cultureName = culture.star_names?.[star.id]
      if (cultureName) {
        rows.push([
          t('objectInspector.cultureName'),
          `${cultureName}（${culture.name}）`,
        ])
      }
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
        {rows.map(([k, v], i) => (
          <div key={`${k}-${i}`} className="contents">
            <dt className="text-gray-500">{k}</dt>
            <dd className="text-gray-200 text-right">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
