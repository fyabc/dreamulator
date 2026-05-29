import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import HomePage from './pages/HomePage'
import WorldInfo from './pages/WorldInfo'
import WorldList from './pages/WorldList'
import WorldDetail from './pages/WorldDetail'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="world-info" element={<WorldInfo />} />
          <Route path="worlds" element={<WorldList />} />
          <Route path="worlds/:worldName" element={<WorldDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
