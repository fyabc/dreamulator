import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { isStaticMode } from '../api/mode'
import { api } from '../api/client'
import AtlasIcon from '../components/AtlasIcon'
import HomeEarth from '../components/HomeEarth'
import { loadLastWorld } from '../utils/lastWorld'

export default function HomePage() {
  const { t } = useTranslation('common')
  const staticMode = isStaticMode()
  const lastWorld = staticMode ? null : loadLastWorld()
  const { data: worlds } = useQuery({ queryKey: ['worlds'], queryFn: api.listWorlds, enabled: !!lastWorld })

  return (
    <div className="atlas-home flex min-h-[calc(100svh-3.5rem)] flex-col bg-space-bg md:min-h-screen">
      <section className="atlas-hero" aria-labelledby="home-heading">
        <HomeEarth />
        <div className="atlas-hero-copy" data-testid={staticMode ? undefined : 'start-actions'}>
          <h1 id="home-heading">
            {t('home.atlas.headlineFirst')}<br />{t('home.atlas.headlineSecond')}
          </h1>
          <p>{t(staticMode ? 'home.atlas.staticIntro' : 'home.atlas.localIntro')}</p>
          <div className="atlas-hero-actions">
            <Link to="/new-world" className="atlas-primary" data-testid="start-create">
              {t('worlds:action.newWorld')} <AtlasIcon name="arrow" />
            </Link>
            <Link to="/worlds" className="atlas-text-action" data-testid="start-explore">
              {t('worlds:start.explore')} <AtlasIcon name="arrow" />
            </Link>
          </div>
        </div>
      </section>
      {lastWorld && worlds?.includes(lastWorld.world) && (
        <div className="atlas-home-links">
          <Link to={lastWorld.path} data-testid="continue-last-world" className="atlas-text-action min-w-0 break-all">
            {t('worlds:start.continueLabel')}: {lastWorld.world}{lastWorld.branch && ` · ${lastWorld.branch}`}
            <AtlasIcon name="arrow" />
          </Link>
        </div>
      )}
      <footer className="atlas-home-footer">
        <span>Dreamulator v{__APP_VERSION__}</span>
        <div className="flex items-center gap-5">
          <Link to="/help">{t('nav.help')}</Link>
          <a href="https://github.com/fyabc/dreamulator">GitHub</a>
        </div>
      </footer>
    </div>
  )
}
