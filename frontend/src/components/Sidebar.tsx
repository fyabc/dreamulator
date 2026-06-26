import { Link, useLocation } from 'react-router-dom'

interface SidebarProps {
  open: boolean
  onClose: () => void
}

export default function Sidebar({ open, onClose }: SidebarProps) {
  const location = useLocation()

  const navItems = [
    { path: '/', label: '首页', icon: '🏠' },
    { path: '/world-info', label: '世界信息', icon: '📋' },
    { path: '/worlds', label: '世界管理', icon: '🌍' },
  ]

  return (
    <aside
      className={[
        'w-60 bg-space-panel flex flex-col flex-shrink-0',
        'border-r border-space-border',
        // Mobile: fixed overlay, hidden by default, slide in when open
        'fixed inset-y-0 left-0 z-40',
        'transition-transform duration-200 ease-in-out',
        open ? 'translate-x-0' : '-translate-x-full',
        // Desktop (md+): static, always visible, no transform
        'md:static md:translate-x-0 md:z-auto',
      ].join(' ')}
    >
      {/* Logo + close button */}
      <div className="p-5 border-b border-space-border flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">
            <span className="logo-dream">dream</span>
            <span className="logo-ulator text-base">ulator</span>
          </h1>
          <p className="text-xs text-gray-500 mt-1 tracking-wider">架空世界推演工具</p>
        </div>
        {/* Close button — mobile only */}
        <button
          onClick={onClose}
          className="md:hidden ml-2 p-1.5 rounded-lg text-gray-500 hover:text-gray-200 hover:bg-space-surface transition-colors"
          aria-label="关闭菜单"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
        {navItems.map((item) => {
          const isActive =
            item.path === '/'
              ? location.pathname === '/'
              : location.pathname.startsWith(item.path)
          return (
            <Link
              key={item.path}
              to={item.path}
              onClick={onClose}
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
