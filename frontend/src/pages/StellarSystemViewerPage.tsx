/**
 * StellarSystemViewerPage — standalone 3D stellar system visualisation.
 *
 * Extracted from WorldDetail's "3D 视图" tab into a first-class route at
 *   /worlds/:worldName/viewer3d
 *
 * Supports branch selection via ?branch= URL search parameter.
 */

import { useParams, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import StellarSystemViewer from '../viewers/StellarSystemViewer'
import BranchSelector from '../components/BranchSelector'

export default function StellarSystemViewerPage() {
  const { worldName } = useParams<{ worldName: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedBranch = searchParams.get('branch') || null

  const setSelectedBranch = (branch: string | null) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (branch) next.set('branch', branch)
      else next.delete('branch')
      return next
    }, { replace: true })
  }

  // --- Data ---

  const { data: stellarSystem, isLoading: loadingStellar } = useQuery({
    queryKey: ['astronomy', worldName, selectedBranch],
    queryFn: () => api.getStellarSystem(worldName!, selectedBranch),
    enabled: !!worldName,
    retry: false,
  })

  const { data: planets, isLoading: loadingPlanets } = useQuery({
    queryKey: ['planets', worldName, selectedBranch],
    queryFn: () => api.getPlanets(worldName!, selectedBranch),
    enabled: !!worldName,
    retry: false,
  })

  const { data: habitableZones } = useQuery({
    queryKey: ['habitable-zones', worldName, selectedBranch],
    queryFn: () => api.getHabitableZones(worldName!, selectedBranch),
    enabled: !!worldName,
    retry: false,
  })

  const isLoading = loadingStellar || loadingPlanets

  // --- Render ---

  if (!worldName) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        未选择世界
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-space-border">
        <h1 className="text-xl font-semibold text-neon-cyan neon-glow-subtle">
          恒星系 3D 可视化
        </h1>
        <BranchSelector
          worldName={worldName}
          selectedBranch={selectedBranch}
          onSelect={setSelectedBranch}
        />
      </div>

      {/* Viewer */}
      <div className="flex-1 relative">
        {isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center text-gray-500">
            加载中...
          </div>
        ) : (
          <StellarSystemViewer
            stellar={stellarSystem}
            planets={planets}
            habitableZones={habitableZones}
          />
        )}
      </div>
    </div>
  )
}
