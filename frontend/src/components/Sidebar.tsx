import { Link, useLocation } from 'react-router-dom'

export default function Sidebar() {
  const location = useLocation()

  const navItems = [
    { path: '/', label: '首页', icon: '🏠' },
    { path: '/world-info', label: '世界信息', icon: '📋' },
    { path: '/worlds', label: '世界管理', icon: '🌍' },
  ]

  return (
    <aside className="w-60 bg-space-panel border-r border-space-border flex flex-col flex-shrink-0">
      {/* Logo */}
      <div className="p-5 border-b border-space-border">
        <h1 className="text-2xl font-bold">
          <span className="logo-dream">dream</span>
          <span className="logo-ulator text-base">ulator</span>
        </h1>
        <p className="text-xs text-gray-500 mt-1 tracking-wider">架空世界推演工具</p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-3 space-y-1">
        {navItems.map((item) => {
          const isActive =
            item.path === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(item.path)
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center gap-3 px-4 py-2.5 rounded-lg transition-all duration-200 ${
                isActive
                  ? 'bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/20 shadow-[0_0_12px_rgba(0,212,255,0.08)]'
                  : 'text-gray-400 hover:bg-space-surface hover:text-gray-200 border border-transparent'
              }`}
            >
              <span className="text-lg">{item.icon}</span>
              <span className="font-medium text-sm">{item.label}</span>
            </Link>
          )
        })}
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-space-border text-xs text-gray-600">
        v0.1.0
      </div>
    </aside>
  )
}
