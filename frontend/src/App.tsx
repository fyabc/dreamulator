import { lazy, Suspense } from 'react'
import { HashRouter, BrowserRouter, Routes, Route, Navigate, useParams, useSearchParams } from 'react-router-dom'
import Layout from './components/Layout'
import { isStaticMode } from './api/mode'

// Keep viewer and documentation dependencies behind their routes.
const HomePage = lazy(() => import('./pages/HomePage'))
const WorldList = lazy(() => import('./pages/WorldList'))
const WorldDetail = lazy(() => import('./pages/WorldDetail'))
const MapViewerPage = lazy(() => import('./pages/MapViewerPage'))
const StellarSystemViewerPage = lazy(() => import('./pages/StellarSystemViewerPage'))
const GlobeViewerPage = lazy(() => import('./pages/GlobeViewerPage'))
const SkyViewerPage = lazy(() => import('./pages/SkyViewerPage'))
const CivMapEditorPage = lazy(() => import('./pages/CivMapEditorPage'))
const PackViewerPage = lazy(() => import('./pages/PackViewerPage'))
const HelpPage = lazy(() => import('./pages/HelpPage'))
const PlaygroundPage = lazy(() => import('./pages/PlaygroundPage'))
const ImportPage = lazy(() => import('./pages/ImportPage'))
const NewWorldPage = lazy(() => import('./pages/NewWorldPage'))
const CreationMapPage = lazy(() => import('./pages/CreationMapPage'))
const MapWorkbenchRoute = lazy(() => import('./pages/MapWorkbenchRoute'))

function PlanetMapRoute() {
  const [search] = useSearchParams()
  return search.get('creation') === '1' ? <CreationMapPage /> : <MapViewerPage />
}

const PageFallback = () => (
  <div className="flex items-center justify-center min-h-[60vh]">
    <div className="animate-spin h-8 w-8 border-4 border-blue-400 border-t-transparent rounded-full" />
  </div>
)

function LegacyProjectLink() {
  const { projectId } = useParams()
  const [current] = useSearchParams()
  const search = new URLSearchParams(current)
  search.set('tab', 'data')
  return <Navigate to={projectId ? `/worlds/${encodeURIComponent(projectId)}?${search}` : '/worlds'} replace />
}

function App() {
  // HashRouter for GitHub Pages (no server-side SPA fallback),
  // BrowserRouter for local dev with FastAPI backend.
  const staticMode = isStaticMode()
  const Router = staticMode ? HashRouter : BrowserRouter
  const base = import.meta.env.BASE_URL

  return (
    <Router basename={!staticMode && base.startsWith('/') ? base : undefined}>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<HomePage />} />
            <Route path="world-info" element={<Navigate to="/worlds" replace />} />
            <Route path="import" element={<ImportPage />} />
            <Route path="new-world" element={<NewWorldPage />} />
            <Route path="worlds" element={<WorldList />} />
            {staticMode && <>
              <Route path="projects" element={<Navigate to="/worlds" replace />} />
              <Route path="projects/:projectId" element={<LegacyProjectLink />} />
            </>}
            <Route path="worlds/:worldName" element={<WorldDetail />} />
            <Route element={<MapWorkbenchRoute />}>
              <Route path="worlds/:worldName/map" element={<MapViewerPage />} />
              <Route path="worlds/:worldName/map/:planetId" element={<PlanetMapRoute />} />
              <Route path="worlds/:worldName/globe/:planetId?" element={<GlobeViewerPage />} />
            </Route>
            <Route path="worlds/:worldName/viewer3d" element={<StellarSystemViewerPage />} />
            {staticMode && <Route path="worlds/:worldName/sky/:bodyId?" element={<SkyViewerPage />} />}
            <Route path="packs" element={<PackViewerPage />} />
            <Route path="playground" element={<PlaygroundPage />} />
            <Route path="help" element={<HelpPage />} />
          </Route>
          {/* Full-page workspaces (no Layout wrapper) */}
          {!staticMode && <Route path="worlds/:worldName/sky/:bodyId?" element={<SkyViewerPage />} />}
          <Route path="worlds/:worldName/civmap" element={<CivMapEditorPage />} />
          <Route path="worlds/:worldName/civmap/:branchName" element={<CivMapEditorPage />} />
        </Routes>
      </Suspense>
    </Router>
  )
}

export default App
