import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import { isStaticMode } from '../api/mode'
import AtlasIcon from '../components/AtlasIcon'
import CreationRaster from '../components/map/CreationRaster'
import { heightmapPlanet } from '../projects/heightmapWorld'
import { worldDataPath } from '../projects/projectStore'

export default function CreationMapPage() {
  const { worldName = '' } = useParams()
  const { t } = useTranslation('worlds')
  const query = useQuery({ queryKey: ['heightmap-creation', worldName], queryFn: () => api.getHeightmapWorld(worldName),
    enabled: !!worldName, retry: false, staleTime: 60_000, gcTime: 30_000 })
  const world = query.data
  return <div className="mx-auto max-w-6xl space-y-5 px-4 py-8 sm:px-8">
    <Link to={worldDataPath(worldName)} className="inline-flex min-h-10 items-center gap-2 text-sm text-gray-300 hover:text-neon-cyan">
      <AtlasIcon name="back" />{t('worldData.title')}
    </Link>
    {query.isPending && <p role="status">{t('status.loading')}</p>}
    {query.isError && <p role="alert" className="text-red-300">{t('status.loadError')}: {query.error.message}</p>}
    {query.isSuccess && !world && <p role="alert">{t('creation.noSavedMap')}</p>}
    {world && <>
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="break-words text-3xl font-semibold">{world.title}</h1>
        {!isStaticMode() && <Link className="text-neon-cyan hover:underline" to={`/worlds/${encodeURIComponent(worldName)}/map/${heightmapPlanet}`}>
          {t('creation.formalMap')}
        </Link>}
      </header>
      <CreationRaster input={world.heightmap} params={world.params} temperature={world.temperature} width={1440} />
      <p className="max-w-2xl text-sm text-gray-400">{t(world.temperature ? 'creation.notFormal' : 'creation.notGenerated')}</p>
    </>}
  </div>
}
