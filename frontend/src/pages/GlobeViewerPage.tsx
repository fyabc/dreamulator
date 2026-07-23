/**
 * GlobeViewerPage — 3D 球面地形可视化.
 *
 * Route: /worlds/:worldName/globe/:planetId
 *
 * Loads elevation data + metadata for the selected planet, generates
 * an equirectangular terrain texture via the same pipeline as the 2D
 * map viewer (useGPUTerrain), and renders it on a 3D sphere.
 */

import { useParams, useSearchParams, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState, useEffect, useMemo, useCallback } from 'react'
import * as THREE from 'three'
import { api } from '../api/client'
import GlobeViewer from '../viewers/GlobeViewer'
import BranchSelector from '../components/BranchSelector'
import useGPUTerrain from '../viewers/map/useGPUTerrain'
import { decodePngToFloat32 } from '../viewers/map/utils/imageCodec'

export default function GlobeViewerPage() {
  const { worldName, planetId } = useParams<{ worldName: string; planetId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const selectedBranch = searchParams.get('branch') || null

  const setSelectedBranch = (branch: string | null) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (branch) next.set('branch', branch)
      else next.delete('branch')
      return next
    }, { replace: true })
  }

  // --- Map metadata ---
  const { data: meta } = useQuery({
    queryKey: ['mapMeta', worldName, planetId, selectedBranch],
    queryFn: () => api.getMapMeta(worldName!, planetId!, selectedBranch),
    enabled: !!worldName && !!planetId,
  })

  // --- Elevation PNG ---
  const { data: elevationBlob, isLoading: loadingElev } = useQuery({
    queryKey: ['elevationBlob', worldName, planetId, selectedBranch],
    queryFn: () => api.getElevationBlob(worldName!, planetId!, selectedBranch),
    enabled: !!worldName && !!planetId,
    retry: false,
  })

  // Decode elevation
  const [elevData, setElevData] = useState<Float32Array | null>(null)
  const [elevDims, setElevDims] = useState<{ w: number; h: number }>({ w: 0, h: 0 })

  useEffect(() => {
    if (!elevationBlob) { setElevData(null); return }
    let cancelled = false
    decodePngToFloat32(elevationBlob).then(({ data, width, height }) => {
      if (!cancelled) { setElevData(data); setElevDims({ w: width, h: height }) }
    })
    return () => { cancelled = true }
  }, [elevationBlob])

  // --- GPU terrain texture ---
  const elevMin = meta?.elevation_min_m ?? -11000
  const elevMax = meta?.elevation_max_m ?? 9000
  const seaLevel = meta?.sea_level_m ?? 0

  const gpuMaterial = useGPUTerrain({
    elevation: elevData,
    width: elevDims.w,
    height: elevDims.h,
    seaLevel,
    elevMinM: elevMin,
    elevMaxM: elevMax,
    colorMode: 'terrain',
  })

  // Extract the texture from the gpuMaterial's uniform
  const terrainTexture = useMemo(() => {
    if (!gpuMaterial) return null
    return (gpuMaterial.uniforms.u_colorMap?.value as THREE.Texture) ?? null
  }, [gpuMaterial])

  // --- Branch-aware search string for links ---
  const branchQS = selectedBranch ? `?branch=${encodeURIComponent(selectedBranch)}` : ''

  // Zoom-out transition → navigate to stellar system view
  const handleTransition = useCallback(() => {
    navigate(`/worlds/${worldName}/viewer3d${branchQS}`)
  }, [navigate, worldName, branchQS])

  // --- Render ---

  if (!worldName || !planetId) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        未选择世界或行星
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-space-border">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-semibold text-neon-cyan neon-glow-subtle">
            3D 球面视图
          </h1>
          <span className="text-sm text-gray-500 font-mono">
            {planetId}
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Back to 2D map */}
          <Link
            to={`/worlds/${worldName}/map/${planetId}${branchQS}`}
            className="px-3 py-1.5 text-xs rounded-lg bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors"
          >
            🗺️ 2D 地图
          </Link>

          {/* Back to stellar system */}
          <Link
            to={`/worlds/${worldName}/viewer3d${branchQS}`}
            className="px-3 py-1.5 text-xs rounded-lg bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors"
          >
            🔭 恒星系
          </Link>

          <BranchSelector
            worldName={worldName}
            selectedBranch={selectedBranch}
            onSelect={setSelectedBranch}
          />
        </div>
      </div>

      {/* Viewer */}
      <div className="flex-1 relative">
        {loadingElev || (elevData && !gpuMaterial) ? (
          <div className="absolute inset-0 flex items-center justify-center text-gray-500">
            {loadingElev ? '加载高度图中...' : '生成纹理中...'}
          </div>
        ) : elevData === null && !loadingElev ? (
          <div className="absolute inset-0 flex items-center justify-center text-gray-500">
            该行星无地图数据
          </div>
        ) : (
          <GlobeViewer texture={terrainTexture} onTransition={handleTransition} />
        )}
      </div>
    </div>
  )
}
