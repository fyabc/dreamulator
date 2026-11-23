import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import AtlasIcon, { type AtlasIconName } from './AtlasIcon'
import LanguageSwitcher from './LanguageSwitcher'
import VersionStamp from './VersionStamp'
import { useDevModeStore } from '../stores/devModeStore'
import { useExperimentalStore } from '../stores/experimentalStore'
import { isStaticMode } from '../api/mode'
import { worldDataPath, worldOverviewPath } from '../projects/projectStore'
import { hasProjectHeightmap } from '../projects/elevationProject'
import { heightmapMapPath } from '../projects/heightmapWorld'
import type { WorldScope } from './world/useWorldScope'

interface SidebarProps {
  open: boolean
  collapsed: boolean
  scope: WorldScope | null
  onClose: () => void
  onToggleCollapse: () => void
}

interface NavigationItem {
  path: string
  label: string
  icon: AtlasIconName
  matchMap?: boolean
  tab?: string
}

interface SidebarHint {
  label: string
  anchor: HTMLElement
  left: number
  top: number
}

export default function Sidebar({
  open,
  collapsed,
  scope,
  onClose,
  onToggleCollapse,
}: SidebarProps) {
  const location = useLocation()
  const { t } = useTranslation()
  const closeButton = useRef<HTMLButtonElement>(null)
  const hintElement = useRef<HTMLDivElement>(null)
  const [hint, setHint] = useState<SidebarHint | null>(null)
  useEffect(() => {
    if (open) closeButton.current?.focus()
  }, [open])
  useEffect(() => {
    setHint(null)
  }, [collapsed, location.pathname])
  useEffect(() => {
    if (!hint) return
    const dismissHint = () => setHint(null)
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') dismissHint()
    }
    window.addEventListener('keydown', dismissOnEscape)
    window.addEventListener('resize', dismissHint)
    return () => {
      window.removeEventListener('keydown', dismissOnEscape)
      window.removeEventListener('resize', dismissHint)
    }
  }, [hint])
  const devMode = useDevModeStore((s) => s.devMode)
  const setDevMode = useDevModeStore((s) => s.setDevMode)
  const experimental = useExperimentalStore((s) => s.experimental)
  const setExperimental = useExperimentalStore((s) => s.setExperimental)

  const navItems: NavigationItem[] = [
    { path: '/', label: t('nav.home'), icon: 'home' },
    { path: '/worlds', label: t('nav.worlds'), icon: 'globe' },
    { path: '/new-world', label: t('worlds:action.newWorld'), icon: 'import' },
  ]
  const utilityItems: NavigationItem[] = [
    { path: '/help', label: t('nav.help'), icon: 'help' },
  ]

  // World-specific nav items (shown when viewing a world)
  // Carry search params (e.g. ?branch=xxx) to preserve branch selection
  const search = new URLSearchParams(location.search)
  const detailTab = search.get('tab') ?? 'overview'
  const branchQuery = scope?.branch ? `?${new URLSearchParams({ branch: scope.branch })}` : ''
  const worldPath = scope ? worldOverviewPath(scope.id) : ''
  const worldNavItems: NavigationItem[] = scope ? [
    { path: `${worldPath}${branchQuery}`, label: t('nav.overview'), icon: 'overview', tab: scope.browserWorld ? 'overview' : undefined },
    ...(!scope.browserWorld || hasProjectHeightmap(scope.browserWorld) ? [{
      path: scope.browserWorld ? heightmapMapPath(scope.id) : `${worldPath}/globe${branchQuery}`,
      label: t('nav.map'), icon: 'globe' as const, matchMap: true,
    }] : []),
    ...(scope.browserWorld
      ? [{ path: worldDataPath(scope.id), label: t('worlds:worldData.title'), icon: 'folder' as const, tab: 'data' }]
      : [{ path: `${worldPath}/viewer3d${branchQuery}`, label: t('nav.viewer3d'), icon: 'system' as const },
        { path: `${worldPath}/sky${branchQuery}`, label: t('nav.sky'), icon: 'stars' as const }]),
  ] : []

  const revealHint = (label: string, anchor: HTMLElement) => {
    if (!collapsed) return
    const { right, top, height } = anchor.getBoundingClientRect()
    setHint({ label, anchor, left: right, top: top + height / 2 })
  }

  const renderNavLinks = (items: NavigationItem[]) => items.map((item) => {
    const path = item.path.split('?')[0]
    const isActive = (location.pathname === path && (!item.tab || item.tab === detailTab)) || (item.matchMap
      && /\/worlds\/[^/]+\/(?:globe|map)(?:\/|$)/.test(location.pathname))
    return (
      <Link
        key={item.path}
        to={item.path}
        onClick={onClose}
        aria-label={collapsed ? item.label : undefined}
        onPointerEnter={(event) => { if (event.pointerType === 'mouse') revealHint(item.label, event.currentTarget) }}
        onPointerLeave={(event) => {
          if (event.currentTarget.matches(':focus-visible') || (event.relatedTarget instanceof Node && hintElement.current?.contains(event.relatedTarget))) return
          setHint(null)
        }}
        onFocus={(event) => { if (event.currentTarget.matches(':focus-visible')) revealHint(item.label, event.currentTarget) }}
        onBlur={() => setHint(null)}
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
  })

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
      <nav className="flex-1 p-3 space-y-1 overflow-y-auto" onScroll={() => setHint(null)}>
        {renderNavLinks(navItems)}
        {/* World-specific nav items */}
        {scope && (
          <div role="group" aria-label={t('context.navigation', { world: scope.name })}
            className="mt-3 space-y-1 border-t border-space-border pt-3">
            <div className={`px-2 pb-1 text-xs font-semibold text-slate-300 ${collapsed ? 'md:hidden' : ''}`}>
              <p className="truncate" title={scope.name}>{scope.name}</p>
            </div>
            {renderNavLinks(worldNavItems)}
          </div>
        )}
        <div className="mt-3 space-y-1 border-t border-space-border pt-3">
          {renderNavLinks(utilityItems)}
        </div>
      </nav>

      {collapsed && hint && createPortal(
        <div ref={hintElement} aria-hidden="true"
          className="fixed z-50 hidden -translate-y-1/2 pl-2 md:block" style={{ left: hint.left, top: hint.top }}
          onPointerLeave={(event) => {
            if (hint.anchor.matches(':focus-visible') || (event.relatedTarget instanceof Node && hint.anchor.contains(event.relatedTarget))) return
            setHint(null)
          }}>
          <span className="block rounded-md border border-space-border bg-space-panel px-3 py-1.5 text-sm text-slate-100">{hint.label}</span>
        </div>,
        document.body,
      )}

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
          <VersionStamp />
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
