import { lazy, Suspense } from 'react'
import { HashRouter, BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import { isStaticMode } from './api/mode'

// Code-split heavy pages: Three.js (~600 KB), Leaflet (~150 KB), and
// react-markdown (~50 KB) are only loaded when the user navigates to the
// relevant page.  This cuts the initial bundle for the home/world-list
// pages by ~60%.
const HomePage = lazy(() => import('./pages/HomePage'))
const WorldList = lazy(() => import('./pages/WorldList'))
const WorldDetail = lazy(() => import('./pages/WorldDetail'))
const MapViewerPage = lazy(() => import('./pages/MapViewerPage'))
const StellarSystemViewerPage = lazy(() => import('./pages/StellarSystemViewerPage'))
const GlobeViewerPage = lazy(() => import('./pages/GlobeViewerPage'))
const CivMapEditorPage = lazy(() => import('./pages/CivMapEditorPage'))
const HelpPage = lazy(() => import('./pages/HelpPage'))

const PageFallback = () => (
  <div className="flex items-center justify-center min-h-[60vh]">
    <div className="animate-spin h-8 w-8 border-4 border-blue-400 border-t-transparent rounded-full" />
  </div>
)

function App() {
  // HashRouter for GitHub Pages (no server-side SPA fallback),
  // BrowserRouter for local dev with FastAPI backend.
  const Router = isStaticMode() ? HashRouter : BrowserRouter

  return (
    <Router>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="world-info" element={<Navigate to="/worlds" replace />} />
            <Route path="worlds" element={<WorldList />} />
            <Route path="worlds/:worldName" element={<WorldDetail />} />
            <Route path="worlds/:worldName/map" element={<MapViewerPage />} />
            <Route path="worlds/:worldName/map/:planetId" element={<MapViewerPage />} />
            <Route path="worlds/:worldName/viewer3d" element={<StellarSystemViewerPage />} />
            <Route path="worlds/:worldName/globe/:planetId" element={<GlobeViewerPage />} />
            <Route path="help" element={<HelpPage />} />
          </Route>
          {/* Full-page editors (no Layout wrapper) */}
          <Route path="worlds/:worldName/civmap" element={<CivMapEditorPage />} />
          <Route path="worlds/:worldName/civmap/:branchName" element={<CivMapEditorPage />} />
        </Routes>
      </Suspense>
    </Router>
  )
}

export default App
