import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import { temperatureSamplesHelpPath, temperatureTrialMapPath } from '../../playground/temperatureDraft'
import { projectButton } from '../projects/SaveProjectResult'

export default function TemperatureTrialEntry({ world, branch, preferred }: {
  world: string
  branch: string | null
  preferred: string | null
}) {
  const { t } = useTranslation('worlds', { keyPrefix: 'temperatureTrial' })
  const maps = useQuery({ queryKey: ['mapPlanets', world, branch], queryFn: () => api.listMapPlanets(world, branch) })
  const catalog = useQuery({ queryKey: ['systemCatalog', world, branch], queryFn: () => api.getSystemCatalog(world, branch), retry: false })
  const [selected, setSelected] = useState<string | null>(null)
  const planets = maps.data ?? []
  const planet = [selected, preferred, catalog.data?.target_body_id, planets[0]].find(value => value && planets.includes(value))

  return <section aria-labelledby="temperature-trial-heading" className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-space-border pb-4">
    <div className="max-w-xl">
      <h2 id="temperature-trial-heading" className="font-semibold text-gray-100">{t('title')}</h2>
      <p className="mt-1 text-sm text-gray-400">{t('description')}</p>
    </div>
    {planet ? <div className="flex flex-wrap items-center gap-2">
      {planets.length > 1 && <select aria-label={t('planet')} value={planet} onChange={event => setSelected(event.target.value)}
        className="min-h-11 max-w-full rounded border border-space-border bg-space-surface px-2 text-sm text-gray-200">
        {planets.map(id => <option key={id} value={id}>{catalog.data?.bodies?.find(body => body.id === id)?.name ?? id}</option>)}
      </select>}
      <Link className={`${projectButton} inline-flex min-h-11 items-center justify-center text-sm`}
        to={temperatureTrialMapPath({ world, branch, planet })}>{t('open')}</Link>
    </div> : maps.isPending ? <p role="status" className="text-sm text-gray-400">{t('loading')}</p>
      : <div className="text-sm">
        <p className="text-gray-400">{t(maps.isError ? 'error' : 'noElevation')}</p>
        {maps.isError ? <button type="button" className="min-h-11 text-neon-cyan hover:underline" onClick={() => void maps.refetch()}>{t('retry')}</button>
          : <Link to={isStaticMode() ? temperatureSamplesHelpPath : '/import'} className="inline-flex min-h-11 items-center text-neon-cyan hover:underline">{t(isStaticMode() ? 'samples' : 'import')}</Link>}
      </div>}
  </section>
}
