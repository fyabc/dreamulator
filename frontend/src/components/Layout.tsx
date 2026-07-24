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
    if (sidebarOpen) closeSidebar()
    else openSidebar()
  }, [sidebarOpen, openSidebar, closeSidebar])

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
        {/* Top bar — mobile only. Desktop: sidebar collapse is self-contained. */}
        <header className="md:hidden flex items-center gap-2 px-3 py-2 bg-space-panel border-b border-space-border sticky top-0 z-20">
          <button
            onClick={handleToggle}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-100 hover:bg-space-surface transition-colors"
            aria-label="切换菜单"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <h1 className="text-sm font-bold">
            <span className="logo-dream">dream</span>
            <span className="logo-ulator text-[10px]">ulator</span>
          </h1>
        </header>

        <main className="flex-1 overflow-auto relative">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
