import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import WorldList from './pages/WorldList'
import WorldDetail from './pages/WorldDetail'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/worlds" replace />} />
          <Route path="worlds" element={<WorldList />} />
          <Route path="worlds/:worldName" element={<WorldDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
