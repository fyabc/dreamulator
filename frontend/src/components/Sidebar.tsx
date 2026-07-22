import { Link, useLocation } from 'react-router-dom'

interface SidebarProps {
  open: boolean
  collapsed: boolean
  onClose: () => void
  onToggleCollapse: () => void
}

export default function Sidebar({
  open,
  collapsed,
  onClose,
  onToggleCollapse,
}: SidebarProps) {
  const location = useLocation()

  // Extract world name from path if we're in a world context
  const worldMatch = location.pathname.match(/^\/worlds\/([^/]+)/)
  const currentWorld = worldMatch ? worldMatch[1] : null

  const navItems = [
    { path: '/', label: '首页', icon: '🏠' },
    { path: '/world-info', label: '世界信息', icon: '📋' },
    { path: '/worlds', label: '世界管理', icon: '🌍' },
  ]

  // World-specific nav items (shown when viewing a world)
  // Carry search params (e.g. ?branch=xxx) to preserve branch selection
  const search = location.search
  const worldNavItems = currentWorld
    ? [
        { path: `/worlds/${currentWorld}${search}`, label: '概览', icon: '📋' },
        { path: `/worlds/${currentWorld}/map${search}`, label: '地图', icon: '🗺️' },
      ]
    : []

  return (
    <aside
      className={[
        'bg-space-panel flex flex-col flex-shrink-0',
        'border-r border-space-border',
        'transition-[width,transform] duration-200 ease-in-out',
        // Mobile: fixed overlay, slide in/out
        'fixed inset-y-0 left-0 z-40 w-60',
        open ? 'translate-x-0' : '-translate-x-full',
        // Desktop: static, collapsible width, always visible
        'md:static md:translate-x-0 md:z-auto',
        collapsed ? 'md:w-16' : 'md:w-60',
      ].join(' ')}
    >
      {/* Logo + close button (mobile) */}
      <div className="p-5 border-b border-space-border flex items-center justify-between min-h-[85px]">
        <div className={collapsed ? 'md:hidden' : ''}>
          <h1 className="text-2xl font-bold">
            <span className="logo-dream">dream</span>
            <span className="logo-ulator text-base">ulator</span>
          </h1>
          <p className="text-xs text-gray-500 mt-1 tracking-wider">架空世界推演工具</p>
        </div>
        {/* Collapsed desktop: small icon */}
        <div className={collapsed ? 'hidden md:block text-center w-full' : 'hidden'}>
          <span className="text-lg font-bold logo-dream">D</span>
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
              title={collapsed ? item.label : undefined}
              className={[
                'flex items-center rounded-lg transition-all duration-200',
                collapsed ? 'md:justify-center md:px-0 md:py-3' : '',
                'px-4 py-2.5 gap-3',
                isActive
                  ? 'bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/20 shadow-[0_0_12px_rgba(0,212,255,0.08)]'
                  : 'text-gray-400 hover:bg-space-surface hover:text-gray-200 border border-transparent',
              ].join(' ')}
            >
              <span className="text-lg flex-shrink-0">{item.icon}</span>
              <span className={['font-medium text-sm', collapsed ? 'md:hidden' : ''].join(' ')}>
                {item.label}
              </span>
            </Link>
          )
        })}

        {/* World-specific nav items */}
        {worldNavItems.length > 0 && (
          <>
            <div className={['pt-3 mt-3 border-t border-space-border', collapsed ? 'md:hidden' : ''].join(' ')}>
              <span className="text-xs text-gray-600 uppercase tracking-wide">{currentWorld}</span>
            </div>
            {worldNavItems.map((item) => {
              const isActive = location.pathname === item.path
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  onClick={onClose}
                  title={collapsed ? item.label : undefined}
                  className={[
                    'flex items-center rounded-lg transition-all duration-200',
                    collapsed ? 'md:justify-center md:px-0 md:py-3' : '',
                    'px-4 py-2.5 gap-3',
                    isActive
                      ? 'bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/20 shadow-[0_0_12px_rgba(0,212,255,0.08)]'
                      : 'text-gray-400 hover:bg-space-surface hover:text-gray-200 border border-transparent',
                  ].join(' ')}
                >
                  <span className="text-lg flex-shrink-0">{item.icon}</span>
                  <span className={['font-medium text-sm', collapsed ? 'md:hidden' : ''].join(' ')}>
                    {item.label}
                  </span>
                </Link>
              )
            })}
          </>
        )}
      </nav>

      {/* Footer with collapse toggle */}
      <div className="p-4 border-t border-space-border">
        {/* Desktop collapse toggle */}
        <button
          onClick={onToggleCollapse}
          className="hidden md:flex items-center w-full px-2 py-2 rounded-lg text-gray-500 hover:text-gray-200 hover:bg-space-surface transition-colors justify-center"
          aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'}
        >
          <svg
            className={`w-5 h-5 transition-transform duration-200 ${collapsed ? 'rotate-180' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 19l-7-7 7-7" />
          </svg>
          <span className={['ml-2 text-xs', collapsed ? 'md:hidden' : ''].join(' ')}>
            收起侧边栏
          </span>
        </button>
        {/* Version — mobile / expanded desktop only */}
        <p className={['text-xs text-gray-600 mt-2 text-center', collapsed ? 'md:hidden' : ''].join(' ')}>
          v0.1.0
        </p>
      </div>
    </aside>
  )
}
