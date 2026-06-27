import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { isStaticMode } from '../api/mode'
import { api } from '../api/client'

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
  const staticMode = isStaticMode()

  const menuItems: MenuItem[] = [
    {
      label: '世界信息',
      description: '查看世界配置与层级数据',
      to: '/world-info',
      icon: '📋',
    },
    {
      label: staticMode ? '世界浏览' : '世界管理',
      description: staticMode ? '浏览已导出的世界数据' : '创建、编辑、删除世界',
      to: '/worlds',
      icon: '🌍',
    },
  ]

  const {
    data: worlds,
    isLoading,
  } = useQuery({
    queryKey: ['worlds'],
    queryFn: api.listWorlds,
  })

  return (
    <div className="relative min-h-screen flex flex-col items-center justify-center px-6">
      {/* Background layers */}
      <div className="starfield" />
      <div className="nebula" />

      {/* Content */}
      <div className="relative z-10 text-center max-w-3xl w-full">
        {/* Logo */}
        <h1 className="text-6xl sm:text-7xl md:text-8xl font-bold tracking-tight mb-2 select-none">
          <span className="logo-dream">dream</span>
          <CircuitDecoration />
          <span className="logo-ulator">ulator</span>
        </h1>

        {/* Subtitle with planet decoration */}
        <div className="flex items-center justify-center gap-2 mb-3">
          <PlanetDecoration />
          <p className="text-gray-400 text-lg tracking-widest">架空世界推演工具</p>
          <PlanetDecoration />
        </div>

        {/* Separator line */}
        <div className="mx-auto mb-10 h-px w-48 bg-gradient-to-r from-transparent via-neon-cyan/30 to-transparent" />

        {/* Quick-entry menu cards */}
        <nav className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-12">
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

        {/* World list */}
        <section className="text-left">
          <h2 className="text-lg font-semibold text-gray-300 mb-4 flex items-center gap-2">
            <span>🌌</span>
            <span>我的世界</span>
          </h2>

          {isLoading && (
            <p className="text-sm text-gray-500 text-center py-6">加载中...</p>
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
                {staticMode ? '暂无已导出的世界数据' : '暂无世界'}
                {!staticMode && (
                  <>
                    {' — '}
                    <Link to="/worlds" className="text-neon-cyan hover:underline">
                      去创建一个 →
                    </Link>
                  </>
                )}
              </p>
            </div>
          )}
        </section>

        {/* Footer */}
        <p className="mt-16 text-xs text-gray-600 tracking-wider">
          v0.1.0 &mdash; Fantasy World Builder
        </p>
      </div>
    </div>
  )
}
