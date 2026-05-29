import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'

export default function Layout() {
  return (
    <div className="flex min-h-screen bg-space-bg text-gray-100">
      <Sidebar />
      <main className="flex-1 overflow-auto relative">
        <Outlet />
      </main>
    </div>
  )
}
