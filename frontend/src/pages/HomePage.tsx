import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { isStaticMode } from '../api/mode'
import { api } from '../api/client'
import StarfieldBackground from '../components/StarfieldBackground'

/**
 * Circuit-node decoration between "dream" and "ulator".
 */
function CircuitDecoration() {
  return (
    <span className="circuit-container mx-1 align-middle">
      <span className="circuit-line" />
      <span className="circuit-node" />
      <span className="circuit-line circuit-line-right" />
    </span>
  )
}

/**
 * Planet decoration referencing the logo's planet-ring 'e' motif.
 */
function PlanetDecoration() {
  return (
    <span className="planet-icon mx-2">
      <span className="planet-body" />
      <span className="planet-ring" />
    </span>
  )
}

interface MenuItem {
  label: string
  description: string
  to: string
  icon: string
}

/**
 * Fetch metadata for a single world (used inside WorldCard).
 */
function WorldCard({ name }: { name: string }) {
  const { data: world } = useQuery({
    queryKey: ['world', name],
    queryFn: () => api.getWorld(name),
    staleTime: 60_000,
  })

  const description: string = world?.metadata?.description ?? ''
  const tags: string[] = world?.metadata?.tags ?? []

  return (
    <Link to={`/worlds/${name}`} className="block group">
      <div className="glass-panel p-5 h-full group-hover:translate-y-[-2px] transition-all duration-300">
        <h3 className="text-lg font-semibold text-neon-cyan neon-glow-subtle group-hover:neon-glow-cyan transition-all">
          {name}
        </h3>
        {description && (
          <p className="text-sm text-gray-400 mt-1.5 leading-relaxed line-clamp-2">
            {description}
          </p>
        )}
        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-3">
            {tags.map((tag) => (
              <span
                key={tag}
                className="text-xs px-2 py-0.5 rounded bg-space-surface/60 text-gray-400 border border-space-border"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>
    </Link>
  )
}

export default function HomePage() {
  const { t } = useTranslation()
  const staticMode = isStaticMode()

  const menuItems: MenuItem[] = [
    {
      label: staticMode ? t('worlds:title.browse') : t('worlds:title.list'),
      description: staticMode ? t('home.menuWorldsDescStatic') : t('home.menuWorldsDescLive'),
      to: '/worlds',
      icon: '🌍',
    },
    {
      label: t('nav.help'),
      description: t('home.menuHelpDesc'),
      to: '/help',
      icon: '📖',
    },
  ]

  // Feature highlight cards (no navigation — visual showcase only)
  // Labels are marketing copy — keep as-is; i18n can come later.
  const features = [
    { icon: '🌐', label: '3D 球面地图', desc: 'GPU 地形渲染，多投影实时切换' },
    { icon: '🌡️', label: '气候模拟', desc: 'EBM 温度 + BFS 水汽 + Köppen 分类' },
    { icon: '🔭', label: '恒星系可视化', desc: '轨道动画、宜居带、行星纹理' },
    { icon: '🧬', label: '生态桥接', desc: 'Whittaker 群系 + NPP + 驯化潜力' },
    { icon: '📜', label: 'AI 叙世', desc: 'Claude 驱动的世界口语化描述' },
    { icon: '🔀', label: '分支系统', desc: 'Git 式层分叉，平行世界推演' },
  ]

  const {
    data: worlds,
    isLoading,
  } = useQuery({
    queryKey: ['worlds'],
    queryFn: api.listWorlds,
  })

  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center px-6 pt-20 md:pt-28">
      {/* Background */}
      <StarfieldBackground />

      {/* Content */}
      <div className="relative z-10 text-center max-w-3xl w-full">
        {/* Logo */}
        <h1 className="text-6xl sm:text-7xl md:text-8xl font-bold tracking-tight mb-2 select-none">
          <span className="logo-dream">dream</span>
          <CircuitDecoration />
          <span className="logo-ulator">ulator</span>
        </h1>

        {/* Subtitle with planet decoration */}
        <div className="flex items-center justify-center gap-2 mb-2">
          <PlanetDecoration />
          <p className="text-gray-400 text-lg tracking-widest">{t('app.subtitle')}</p>
          <PlanetDecoration />
        </div>

        {/* Social / project links */}
        <div className="flex items-center justify-center gap-4 mb-10">
          <a
            href="https://github.com/fyabc/dreamulator"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-neon-cyan transition-colors"
            title="GitHub"
          >
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <path fillRule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
            </svg>
            GitHub
          </a>
        </div>

        {/* Separator line */}
        <div className="mx-auto mb-10 h-px w-48 bg-gradient-to-r from-transparent via-neon-cyan/30 to-transparent" />

        {/* Quick-entry menu cards */}
        <nav className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-10">
          {menuItems.map((item) => (
            <Link key={item.label} to={item.to} className="block group">
              <div className="glass-panel p-5 group-hover:translate-y-[-2px] transition-all duration-300">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-lg">{item.icon}</span>
                  <h3 className="text-lg font-semibold text-neon-cyan neon-glow-subtle group-hover:neon-glow-cyan transition-all">
                    {item.label}
                  </h3>
                </div>
                <p className="text-sm text-gray-400 mt-1">{item.description}</p>
              </div>
            </Link>
          ))}
        </nav>

        {/* Feature highlights */}
        <section className="mb-10">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">
            {t('home.featuresTitle')}
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {features.map((f) => (
              <div
                key={f.label}
                className="glass-panel p-4 text-center group hover:border-neon-cyan/20 transition-colors"
              >
                <div className="text-2xl mb-1.5">{f.icon}</div>
                <h4 className="text-sm font-medium text-gray-200 mb-0.5">{f.label}</h4>
                <p className="text-xs text-gray-500 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* Quick start (new users) */}
        {!staticMode && (
          <section className="mb-10 text-left">
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider mb-4">
              {t('home.quickStartTitle')}
            </h2>
            <div className="glass-panel p-5">
              <ol className="space-y-3 text-sm text-gray-300">
                <li className="flex gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-neon-cyan/15 text-neon-cyan text-xs font-bold flex items-center justify-center">1</span>
                  <span>
                    <Link to="/worlds" className="text-neon-cyan hover:underline font-medium">{t('home.step1Title')}</Link>
                    <span className="text-gray-500"> — {t('home.step1Desc')}</span>
                  </span>
                </li>
                <li className="flex gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-neon-cyan/15 text-neon-cyan text-xs font-bold flex items-center justify-center">2</span>
                  <span>
                    <span className="font-medium">{t('home.step2Title')}</span>
                    <span className="text-gray-500"> — CLI </span>
                    <code className="text-xs bg-space-surface px-1.5 py-0.5 rounded text-neon-cyan/80 font-mono">dreamulator build &lt;world&gt;</code>
                    <span className="text-gray-500"> {t('home.step2Desc')}</span>
                  </span>
                </li>
                <li className="flex gap-3">
                  <span className="flex-shrink-0 w-6 h-6 rounded-full bg-neon-cyan/15 text-neon-cyan text-xs font-bold flex items-center justify-center">3</span>
                  <span>
                    <span className="font-medium">{t('home.step3Title')}</span>
                    <span className="text-gray-500"> — {t('home.step3Desc')}</span>
                  </span>
                </li>
              </ol>
            </div>
          </section>
        )}

        {/* World list */}
        <section className="text-left">
          <h2 className="text-lg font-semibold text-gray-300 mb-4 flex items-center gap-2">
            <span>🌌</span>
            <span>{t('home.myWorlds')}</span>
          </h2>

          {isLoading && (
            <p className="text-sm text-gray-500 text-center py-6">{t('status.loading')}</p>
          )}

          {!isLoading && worlds && worlds.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {worlds.map((name) => (
                <WorldCard key={name} name={name} />
              ))}
            </div>
          )}

          {!isLoading && (!worlds || worlds.length === 0) && (
            <div className="glass-panel p-6 text-center">
              <p className="text-gray-500 text-sm">
                {staticMode ? t('worlds:status.noWorldsStatic') : t('worlds:status.noWorlds')}
                {!staticMode && (
                  <>
                    {' — '}
                    <Link to="/worlds" className="text-neon-cyan hover:underline">
                      {t('worlds:action.goCreate')}
                    </Link>
                  </>
                )}
              </p>
            </div>
          )}
        </section>

        {/* Footer */}
        <p className="mt-16 text-xs text-gray-600 tracking-wider">
          v{__APP_VERSION__} &mdash; {t('app.subtitle')} &mdash; {t('home.footerBuilt')} {__BUILD_DATE__}
        </p>
      </div>
    </div>
  )
}
