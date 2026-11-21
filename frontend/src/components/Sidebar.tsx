import { useEffect, useRef } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import AtlasIcon, { type AtlasIconName } from './AtlasIcon'
import LanguageSwitcher from './LanguageSwitcher'
import { useDevModeStore } from '../stores/devModeStore'
import { useExperimentalStore } from '../stores/experimentalStore'
import { isStaticMode } from '../api/mode'
import { useQuery } from '@tanstack/react-query'
import { getProject, projectKey, worldDataPath } from '../projects/projectStore'

interface SidebarProps {
  open: boolean
  collapsed: boolean
  onClose: () => void
  onToggleCollapse: () => void
}

interface NavigationItem {
  path: string
  label: string
  icon: AtlasIconName
}

export default function Sidebar({
  open,
  collapsed,
  onClose,
  onToggleCollapse,
}: SidebarProps) {
  const location = useLocation()
  const { t } = useTranslation()
  const closeButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (open) closeButton.current?.focus()
  }, [open])
  const devMode = useDevModeStore((s) => s.devMode)
  const setDevMode = useDevModeStore((s) => s.setDevMode)
  const experimental = useExperimentalStore((s) => s.experimental)
  const setExperimental = useExperimentalStore((s) => s.setExperimental)

  // Extract world name from path if we're in a world context
  const worldMatch = location.pathname.match(/^\/worlds\/([^/]+)/)
  const currentWorld = worldMatch ? worldMatch[1] : null
  const browserWorld = useQuery({ queryKey: projectKey(currentWorld ?? ''), queryFn: () => getProject(currentWorld!),
    enabled: isStaticMode() && !!currentWorld, retry: false })

  const navItems: NavigationItem[] = [
    { path: '/', label: t('nav.home'), icon: 'home' },
    { path: '/worlds', label: t('nav.worlds'), icon: 'globe' },
    ...(isStaticMode() ? [] : [{ path: '/import', label: t('nav.import'), icon: 'import' as const }]),
    // Region pack QA page — local packs only, hidden in the static build.
    ...(isStaticMode() ? [] : [{ path: '/packs', label: t('nav.packs'), icon: 'frame' as const }]),
    // Experimental browser Pyodide playground — opt-in via the experimental flag.
    ...(experimental ? [{ path: '/playground', label: t('nav.playground'), icon: 'flask' as const }] : []),
    { path: '/help', label: t('nav.help'), icon: 'help' },
  ]

  // World-specific nav items (shown when viewing a world)
  // Carry search params (e.g. ?branch=xxx) to preserve branch selection
  const search = location.search
  const overviewSearch = new URLSearchParams()
  const branch = new URLSearchParams(search).get('branch')
  if (branch) overviewSearch.set('branch', branch)
  const worldNavItems: NavigationItem[] = currentWorld && browserWorld.data && !browserWorld.data.published
    ? [{ path: worldDataPath(currentWorld), label: t('worlds:worldData.title'), icon: 'folder' }]
    : currentWorld
    ? [
        { path: `/worlds/${currentWorld}${branch ? `?${overviewSearch}` : ''}`, label: t('nav.overview'), icon: 'overview' },
        { path: `/worlds/${currentWorld}/globe${search}`, label: t('nav.map'), icon: 'globe' },
        { path: `/worlds/${currentWorld}/viewer3d${search}`, label: t('nav.viewer3d'), icon: 'orbit' },
        // API-only view (parameterized engine query) — hidden in static mode.
        ...(isStaticMode()
          ? []
          : [{ path: `/worlds/${currentWorld}/sky${search}`, label: t('nav.sky'), icon: 'stars' as const }]),
      ]
    : []

  return (
    <aside
      id="site-sidebar"
      className={[
        'bg-space-panel flex flex-col flex-shrink-0',
        'border-r border-space-border',
        'transition-[width,transform] duration-200 ease-in-out',
        // Mobile: fixed overlay, slide in/out
        'fixed inset-y-0 left-0 z-40 w-60',
        open ? 'translate-x-0' : 'invisible -translate-x-full md:visible',
        // Desktop: sticky so the footer (collapse toggle + version) is always at
        // the viewport bottom regardless of page height.
        'md:sticky md:top-0 md:h-screen md:translate-x-0 md:z-auto',
        collapsed ? 'md:w-16' : 'md:w-60',
      ].join(' ')}
    >
      {/* Logo + close button (mobile) */}
      <div className={`flex min-h-16 items-center justify-between border-b border-space-border ${collapsed ? 'px-4 md:justify-center md:px-1' : 'px-4'}`}>
        <Link to="/" onClick={onClose} aria-label="Dreamulator"
          className="inline-flex min-h-11 items-center gap-2 text-lg font-semibold tracking-tight">
          <AtlasIcon name="orbit" className="size-6 text-neon-cyan" />
          <span className={collapsed ? 'md:hidden' : ''}>Dreamulator</span>
        </Link>
        {/* Close button — mobile only */}
        <button
          ref={closeButton}
          onClick={onClose}
          className="md:hidden inline-flex size-11 items-center justify-center rounded text-gray-300 hover:bg-space-surface"
          aria-label={t('action.close')}
        >
          <AtlasIcon name="close" />
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
              aria-current={location.pathname === item.path ? 'page' : undefined}
              className={[
                'flex items-center rounded-lg transition-all duration-200',
                collapsed ? 'md:justify-center md:px-0 md:py-3' : '',
                'px-4 py-2.5 gap-3',
                isActive
                  ? 'bg-space-surface text-neon-cyan border border-space-border'
                  : 'text-gray-400 hover:bg-space-surface hover:text-gray-200 border border-transparent',
              ].join(' ')}
            >
              <AtlasIcon name={item.icon} />
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
              const path = item.path.split('?')[0]
              const isActive = location.pathname === path || (item.icon === 'globe'
                && /\/worlds\/[^/]+\/(?:globe|map)(?:\/|$)/.test(location.pathname))
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  onClick={onClose}
                  title={collapsed ? item.label : undefined}
                  aria-current={isActive ? 'page' : undefined}
                  className={[
                    'flex items-center rounded-lg transition-all duration-200',
                    collapsed ? 'md:justify-center md:px-0 md:py-3' : '',
                    'px-4 py-2.5 gap-3',
                    isActive
                      ? 'bg-space-surface text-neon-cyan border border-space-border'
                      : 'text-gray-400 hover:bg-space-surface hover:text-gray-200 border border-transparent',
                  ].join(' ')}
                >
                  <AtlasIcon name={item.icon} />
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
          className="hidden md:flex items-center w-full px-2 py-2 rounded-lg text-gray-400 hover:text-gray-200 hover:bg-space-surface transition-colors justify-center"
          aria-label={collapsed ? t('action.expandSidebar') : t('action.collapseSidebar')}
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
            {t('action.collapseSidebar')}
          </span>
        </button>
        {/* Version — auto-injected from package.json at build time */}
        <p className={['text-xs text-gray-400 mt-2 text-center', collapsed ? 'md:hidden' : ''].join(' ')}>
          v{__APP_VERSION__}
        </p>
        {/* Language switcher */}
        <div className={collapsed ? 'md:hidden' : ''}>
          <LanguageSwitcher />
        </div>
        {/* Developer-mode toggle — reveals diagnostic layers (ΔT/ΔP error heatmaps).
            Hidden in static mode: the public read-only release has no diagnostic
            layers to expose. */}
        {!isStaticMode() && (
          <div className={['mt-2', collapsed ? 'md:hidden' : ''].join(' ')}>
            <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
              <input
                type="checkbox"
                checked={devMode}
                onChange={(e) => setDevMode(e.target.checked)}
                className="h-3.5 w-3.5"
              />
              <span>{t('devMode.toggle')}</span>
            </label>
          </div>
        )}
        {/* Experimental-features toggle — reveals features still under
            development (UCC climate layer + cell climate descriptors).  Hidden
            in static mode along with the features it gates. */}
        {!isStaticMode() && (
          <div className={['mt-2', collapsed ? 'md:hidden' : ''].join(' ')}>
            <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
              <input
                type="checkbox"
                checked={experimental}
                onChange={(e) => setExperimental(e.target.checked)}
                className="h-3.5 w-3.5"
              />
              <span>{t('experimental.toggle')}</span>
            </label>
          </div>
        )}
      </div>
    </aside>
  )
}
