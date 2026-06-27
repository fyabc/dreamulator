import { useState, useCallback } from 'react'
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'

export default function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem('sidebar-collapsed') === 'true',
  )

  const openSidebar = useCallback(() => setSidebarOpen(true), [])
  const closeSidebar = useCallback(() => setSidebarOpen(false), [])
  const toggleCollapse = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev
      localStorage.setItem('sidebar-collapsed', String(next))
      return next
    })
  }, [])

  const handleToggle = useCallback(() => {
    // Mobile: toggle overlay; Desktop: toggle collapse
    if (window.innerWidth >= 768) {
      toggleCollapse()
    } else if (sidebarOpen) {
      closeSidebar()
    } else {
      openSidebar()
    }
  }, [sidebarOpen, openSidebar, closeSidebar, toggleCollapse])

  return (
    <div className="flex min-h-screen bg-space-bg text-gray-100">
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
        onClose={closeSidebar}
        onToggleCollapse={toggleCollapse}
      />

      <div className="flex flex-col flex-1 min-w-0">
        {/* Top bar */}
        <header className="flex items-center gap-3 px-4 py-3 bg-space-panel border-b border-space-border sticky top-0 z-20">
          <button
            onClick={handleToggle}
            className="p-2 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-space-surface transition-colors"
            aria-label="切换菜单"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          {/* Title — mobile only (desktop already shows logo in sidebar) */}
          <h1 className="md:hidden text-base font-bold">
            <span className="logo-dream">dream</span>
            <span className="logo-ulator text-xs">ulator</span>
          </h1>
          <div className="flex-1 md:hidden" />
        </header>

        <main className="flex-1 overflow-auto relative">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
