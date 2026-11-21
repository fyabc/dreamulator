import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { savedClimateKey, savedClimateMapPath } from '../../api/climateTrials'
import { projectsKey } from '../../projects/projectStore'
import AtlasIcon from '../AtlasIcon'

export default function SavedClimateTrials({ world }: { world: string }) {
  const { t, i18n } = useTranslation('playground')
  const client = useQueryClient()
  const queryKey = savedClimateKey(world)
  const query = useQuery({ queryKey, queryFn: () => api.listSavedClimateTrials(world), retry: false })
  const erase = useMutation({ mutationFn: (id: string) => api.deleteSavedClimateTrial(world, id),
    onSuccess: () => Promise.all([client.invalidateQueries({ queryKey }), client.invalidateQueries({ queryKey: projectsKey })]) })
  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' })
  const number = new Intl.NumberFormat(i18n.language)

  return <section aria-label={t('ebm.saved.list')} className="max-w-2xl space-y-2 border-b border-space-border pb-4 text-sm">
    <h2 className="font-semibold text-gray-200">{t('ebm.saved.list')}</h2>
    {query.isPending && <p role="status" className="text-gray-400">{t('ebm.saved.loading')}</p>}
    {query.isError && <p role="alert" className="text-red-200">{t('ebm.saved.loadFailed')}</p>}
    {query.data?.length === 0 && <p className="text-gray-400">{t('ebm.saved.empty')}</p>}
    {!!query.data?.length && <ul className="divide-y divide-space-border border-y border-space-border">
      {query.data.map(result => {
        const label = t('ebm.saved.entry', { planet: result.planet, date: date.format(new Date(result.saved_at)) })
        return <li key={result.id} className="flex items-center gap-2 py-1">
          <Link to={savedClimateMapPath(world, result)} className="flex min-h-11 min-w-0 flex-1 items-center justify-between gap-2 rounded px-2 hover:bg-space-surface">
            <span className="min-w-0 break-words">
              <span className="block font-medium text-gray-200">{label}</span>
              <span className="block text-xs text-gray-400">{t('ebm.saved.scope', { branch: result.branch ?? t('trial.root'), cells: number.format(result.cells) })}</span>
            </span>
            <AtlasIcon name="arrow" className="size-4 shrink-0 text-neon-cyan" />
          </Link>
          <button type="button" disabled={erase.isPending} aria-label={t('ebm.saved.deleteNamed', { name: label })}
            className="min-h-11 shrink-0 px-2 text-xs text-red-300 hover:underline disabled:opacity-50"
            onClick={() => { if (window.confirm(t('ebm.saved.deleteNamed', { name: label }))) erase.mutate(result.id) }}>
            {t('ebm.saved.delete')}
          </button>
        </li>
      })}
    </ul>}
    {erase.isError && <p role="alert" className="text-red-200">{t('ebm.saved.deleteFailed')}</p>}
  </section>
}
