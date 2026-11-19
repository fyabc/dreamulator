import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { isStaticMode } from '../../api/mode'

export default function AwaitingBuildBanner({ world, branch }: { world: string; branch: string | null }) {
  const { t } = useTranslation('map')
  const branchQuery = branch ? `?${new URLSearchParams({ branch })}` : ''
  return (
    <div className="bg-sky-900/20 border-b border-sky-700/30 px-4 py-2 text-sm text-sky-200 text-center" data-testid="awaiting-build">
      {t('label.awaitingBuild')}
      {!isStaticMode() && (
        <Link className="ml-2 font-semibold text-neon-cyan underline" to={`/worlds/${encodeURIComponent(world)}${branchQuery}#build`}>
          {t('action.openBuild')}
        </Link>
      )}
    </div>
  )
}
