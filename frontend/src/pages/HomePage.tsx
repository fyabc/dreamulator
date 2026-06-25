import { Link } from 'react-router-dom'
import { isStaticMode } from '../api/mode'

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
  active: boolean
}

export default function HomePage() {
  const staticMode = isStaticMode()

  const menuItems: MenuItem[] = [
    {
      label: '世界信息',
      description: '查看世界配置与层级数据',
      to: '/world-info',
      active: true,
    },
    {
      label: staticMode ? '世界浏览' : '世界管理',
      description: staticMode ? '浏览已导出的世界数据' : '创建、编辑、删除世界',
      to: '/worlds',
      active: true,
    },
    {
      label: '模拟引擎',
      description: '运行物理推演引擎',
      to: '#',
      active: false,
    },
    {
      label: '可视化',
      description: '3D 星图与行星渲染',
      to: '#',
      active: false,
    },
  ]

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
        <div className="mx-auto mb-12 h-px w-48 bg-gradient-to-r from-transparent via-neon-cyan/30 to-transparent" />

        {/* Menu grid */}
        <nav className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {menuItems.map((item) => (
            <MenuCard key={item.label} item={item} />
          ))}
        </nav>

        {/* Footer */}
        <p className="mt-16 text-xs text-gray-600 tracking-wider">
          v0.1.0 &mdash; Fantasy World Builder
        </p>
      </div>
    </div>
  )
}

function MenuCard({ item }: { item: MenuItem }) {
  if (!item.active) {
    return (
      <div className="glass-panel p-5 opacity-40 cursor-not-allowed">
        <h3 className="text-lg font-semibold text-gray-500">{item.label}</h3>
        <p className="text-sm text-gray-600 mt-1">{item.description}</p>
        <span className="text-xs text-gray-600 mt-2 inline-block">即将推出</span>
      </div>
    )
  }

  return (
    <Link to={item.to} className="block group">
      <div className="glass-panel p-5 group-hover:translate-y-[-2px] transition-all duration-300">
        <h3 className="text-lg font-semibold text-neon-cyan neon-glow-subtle group-hover:neon-glow-cyan transition-all">
          {item.label}
        </h3>
        <p className="text-sm text-gray-400 mt-1">{item.description}</p>
      </div>
    </Link>
  )
}
