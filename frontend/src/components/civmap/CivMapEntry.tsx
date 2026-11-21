import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import * as api from '../../api/civmapClient'
import { isStaticMode } from '../../api/mode'
import { staticApi } from '../../api/staticClient'
import AtlasIcon from '../AtlasIcon'

export default function CivMapEntry({ world, branch }: { world: string; branch: string | null }) {
  const { t } = useTranslation('civmap')
  const staticMode = isStaticMode()
  const { data: territory, isFetched: territoryChecked } = useQuery({
    queryKey: ['civmap', 'territory', world, branch],
    queryFn: () => staticMode ? staticApi.getCivTerritory(world, branch) : api.getTerritory(world, branch),
    retry: false,
  })
  const hasTerritory = !!(territory?.countries.length || territory?.snapshots.length)
  const { data: levels } = useQuery({
    queryKey: ['civmap', 'levels', world, branch],
    queryFn: () => api.getAvailableLevels(world, branch),
    enabled: !staticMode && territoryChecked && !hasTerritory,
    retry: false,
  })

  if (!hasTerritory && !levels?.includes('adm1')) return null

  const base = `/worlds/${encodeURIComponent(world)}/civmap`
  return (
    <Link to={branch ? `${base}/${encodeURIComponent(branch)}` : base}
      className="inline-flex min-h-11 items-center gap-2 self-start rounded-lg border border-space-border bg-space-panel px-4 text-sm font-medium text-neon-cyan hover:bg-space-surface">
      <AtlasIcon name="flag" className="size-4" />
      {t('action.openMap')}
      <AtlasIcon name="arrow" className="size-4" />
    </Link>
  )
}
