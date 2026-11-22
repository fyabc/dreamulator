import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import type { ClimateTrialResult } from '../api/climateTrials'

export default function SavedClimateLab({ search, onResult, onShow, onError }: {
  search: URLSearchParams
  onResult: (result: ClimateTrialResult) => void
  onShow: () => void
  onError: () => void
}) {
  const { t, i18n } = useTranslation('playground')
  const [locationSearch] = useSearchParams()
  const world = search.get('world') ?? ''
  const planet = search.get('planet') ?? ''
  const branch = search.get('branch')
  const id = search.get('climateResult') ?? ''
  const query = useQuery({
    queryKey: ['saved-climate-trial', world, planet, branch, id],
    queryFn: () => api.getSavedClimateTrial(world, planet, branch, id),
    staleTime: Infinity, gcTime: 0, retry: false,
  })
  const reported = useRef<ClimateTrialResult | null>(null)
  useEffect(() => {
    if (query.isError) onError()
  }, [query.isError, onError])
  useEffect(() => {
    if (!query.data || reported.current === query.data) return
    reported.current = query.data
    onResult(query.data)
  }, [query.data, onResult])

  const next = new URLSearchParams(locationSearch)
  next.delete('climateResult')
  next.set('trial', 'climate')
  const worldData = new URLSearchParams({ tab: 'data' })
  if (branch) worldData.set('branch', branch)
  const metadata = query.data?.saved?.metadata
  const format = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 2 })

  return <div className="space-y-3 text-xs text-gray-300">
    {query.isPending && <p role="status">{t('ebm.saved.loading')}</p>}
    {query.isError && <p role="alert" className="text-red-200">{t('ebm.saved.loadFailed')}</p>}
    {metadata && <>
      <p>{t('ebm.saved.restoredHelp')}</p>
      <dl className="space-y-1.5 border-y border-space-border py-2 tabular-nums">
        {[
          [t('ebm.model.label'), `EBM ${metadata.inputs.solver_version}`],
          [t('params.tilt'), format.format(metadata.inputs.forcing.axial_tilt_deg)],
          [t('params.rotation'), format.format(metadata.inputs.forcing.rotation_period_days)],
          [t('params.albedo'), format.format(metadata.inputs.forcing.albedo)],
          [t('params.greenhouse'), format.format(metadata.inputs.forcing.greenhouse_warming_k)],
        ].map(([label, value]) => <div key={label} className="flex justify-between gap-2"><dt>{label}</dt><dd className="text-gray-100">{value}</dd></div>)}
      </dl>
      <p>{t('ebm.ready', { cells: format.format(metadata.cells), seconds: format.format(metadata.elapsed_seconds) })}</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={onShow} className="atlas-tool-button min-h-9 text-xs">{t('ebm.show')}</button>
      </div>
    </>}
    {!query.isPending && <Link to={`?${next}`} className="atlas-tool-button min-h-9 text-xs">{t('ebm.saved.newTrial')}</Link>}
    <Link to={`/worlds/${encodeURIComponent(world)}?${worldData}`} className="inline-flex min-h-9 items-center text-neon-cyan hover:underline">{t('trial.openData')}</Link>
  </div>
}
