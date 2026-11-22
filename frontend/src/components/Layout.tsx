import { useState, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Outlet, useLocation } from 'react-router-dom'
import AtlasIcon from './AtlasIcon'
import Sidebar from './Sidebar'
import WorkflowTutorial from '../tutorial/WorkflowTutorial'
import WorldContext from './world/WorldContext'
import { useWorldScope } from './world/useWorldScope'

export default function Layout() {
  const { t } = useTranslation()
  const scope = useWorldScope()
  const { pathname } = useLocation()
  const viewerPage = /^\/worlds\/[^/]+\/(map|globe)(\/|$)/.test(pathname)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const main = useRef<HTMLElement>(null)
  const menu = useRef<HTMLButtonElement>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem('sidebar-collapsed') === 'true',
  )

  const openSidebar = useCallback(() => setSidebarOpen(true), [])
  const closeSidebar = useCallback(() => {
    setSidebarOpen(false)
    if (sidebarOpen) menu.current?.focus()
  }, [sidebarOpen])
  const toggleCollapse = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev
      localStorage.setItem('sidebar-collapsed', String(next))
      return next
    })
  }, [])

  const handleToggle = useCallback(() => {
    if (sidebarOpen) closeSidebar()
    else openSidebar()
  }, [sidebarOpen, openSidebar, closeSidebar])

  return (
    <div className="atlas-shell flex min-h-screen bg-space-bg text-gray-100" onKeyDown={(event) => {
      if (event.key === 'Escape' && sidebarOpen && !event.defaultPrevented) {
        closeSidebar()
      }
    }}>
      <a href="#main-content" onClick={(event) => {
        event.preventDefault()
        main.current?.focus()
      }} className="sr-only z-[60] bg-space-panel p-3 text-neon-cyan focus:not-sr-only focus:fixed focus:left-2 focus:top-2">
        {t('action.skipToContent')}
      </a>
      {/* Mobile backdrop — click to close sidebar */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 md:hidden"
          onClick={closeSidebar}
        />
      )}

      <Sidebar
        open={sidebarOpen}
        collapsed={sidebarCollapsed}
        scope={scope}
        onClose={closeSidebar}
        onToggleCollapse={toggleCollapse}
      />

      <div className={`${scope ? 'atlas-world-shell' : ''} flex flex-col flex-1 min-w-0`}>
        {/* Top bar — mobile only. Desktop: sidebar collapse is self-contained. */}
        <header className="md:hidden flex h-14 shrink-0 items-center gap-2 px-3 bg-space-panel border-b border-space-border sticky top-0 z-20">
          <button
            ref={menu}
            type="button"
            onClick={handleToggle}
            className="inline-flex size-11 items-center justify-center rounded text-gray-300 hover:bg-space-surface"
            aria-label={t('action.toggleMenu')}
            aria-expanded={sidebarOpen}
            aria-controls="site-sidebar"
          >
            <AtlasIcon name="menu" />
          </button>
          <Link to="/" className="inline-flex min-h-11 items-center gap-2 text-base font-semibold tracking-tight">
            <AtlasIcon name="orbit" className="size-5 text-neon-cyan" /> Dreamulator
          </Link>
        </header>

        {scope && <div className={`sticky top-14 z-20 flex h-9 shrink-0 items-center border-b border-space-border bg-space-panel px-3 sm:px-5 md:top-0 ${viewerPage ? 'xl:hidden' : ''}`}>
          <WorldContext scope={scope} />
        </div>}

        <main id="main-content" ref={main} tabIndex={-1} className="flex-1 overflow-auto relative">
          <Outlet />
        </main>
        <WorkflowTutorial />
      </div>
    </div>
  )
}
