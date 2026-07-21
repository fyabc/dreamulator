import { HashRouter, BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import WorldInfo from './pages/WorldInfo'
import WorldList from './pages/WorldList'
import WorldDetail from './pages/WorldDetail'
import MapViewerPage from './pages/MapViewerPage'
import CivMapEditorPage from './pages/CivMapEditorPage'
import { isStaticMode } from './api/mode'

function App() {
  // HashRouter for GitHub Pages (no server-side SPA fallback),
  // BrowserRouter for local dev with FastAPI backend.
  const Router = isStaticMode() ? HashRouter : BrowserRouter

  return (
    <Router>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="world-info" element={<WorldInfo />} />
          <Route path="worlds" element={<WorldList />} />
          <Route path="worlds/:worldName" element={<WorldDetail />} />
          <Route path="worlds/:worldName/map" element={<MapViewerPage />} />
          <Route path="worlds/:worldName/map/:planetId" element={<MapViewerPage />} />
        </Route>
        {/* Full-page editors (no Layout wrapper) */}
        <Route path="worlds/:worldName/civmap" element={<CivMapEditorPage />} />
        <Route path="worlds/:worldName/civmap/:branchName" element={<CivMapEditorPage />} />
      </Routes>
    </Router>
  )
}

export default App
