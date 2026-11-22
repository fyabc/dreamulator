import { useQueries, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { availableRegionPacks, matchingRegionPacks, type RegionWindow } from '../map/regionWindow'

export function RegionDataSourceSelect({ current, results, onChange }: {
  current: string
  results: readonly { name: string; label: string }[]
  onChange: (source: string) => void
}) {
  const { t } = useTranslation('map')
  return <label className="flex w-full min-w-0 items-center gap-2 lg:w-auto">
    <span className="shrink-0 text-xs text-gray-300">{t('packs.results.label')}</span>
    <select value={current} disabled={!results.length} onChange={event => onChange(event.target.value)}
      className="min-h-11 min-w-0 flex-1 truncate rounded border border-space-border bg-space-surface px-2 text-sm text-gray-100 focus-visible:outline focus-visible:outline-neon-cyan disabled:text-gray-400 lg:min-h-9 lg:max-w-80 lg:text-xs">
      <option value="">{t('packs.results.original')}</option>
      {results.map(({ name, label }) => <option key={name} value={name}>
        {results.some(other => other.name !== name && other.label === label) ? `${label} · ${name.slice(-8)}` : label}
      </option>)}
    </select>
  </label>
}

export default function RegionResultSelector({ world, planet, branch, radiusKm, selection, globalReturn }: {
  world: string; planet: string; branch: string | null; radiusKm: number; selection: RegionWindow; globalReturn: string
}) {
  const { t } = useTranslation('map')
  const [params, setParams] = useSearchParams()
  const current = params.get('pack') ?? ''
  const packs = useQuery({ queryKey: ['packs'], queryFn: api.listPacks, retry: false })
  const matches = matchingRegionPacks(availableRegionPacks(packs.data ?? [], { world, planet, branch }, radiusKm), selection, radiusKm)
  const names = matches.map(pack => pack.name)
  if (current && !names.includes(current)) names.push(current)
  const metadata = useQueries({ queries: names.map(name => ({ queryKey: ['packMeta', name], queryFn: () => api.getPackMeta(name), retry: false })) })
  const results = names.map((name, index) => {
    const meta = metadata[index].data
    const mode = meta?.refined?.mode
    const method = mode === 'redraw' || mode === 'blend' || mode === 'hydrology' ? t(`packs.results.${mode}`) : t('packs.results.saved')
    const label = meta?.condition_layers?.grid.length ? t('packs.results.withGrid', { method })
      : meta?.refined?.td_revision ? t('packs.results.withoutGrid', { method }) : method
    return { name, label }
  })

  return <RegionDataSourceSelect current={current} results={results} onChange={source => {
    const next = new URLSearchParams(params)
    if (source) next.set('pack', source)
    else next.delete('pack')
    setParams(next, { state: { regionReturn: globalReturn } })
  }} />
}
