/**
 * StellarSystemViewerPage — standalone 3D stellar system visualisation.
 *
 * Extracted from WorldDetail's "3D 视图" tab into a first-class route at
 *   /worlds/:worldName/viewer3d
 *
 * Supports branch selection via ?branch= URL search parameter.
 *
 * Route C (planet terrain textures): loads elevation data for every planet
 * that has map data and generates a low-res equirectangular texture so the
 * planet sphere shows real terrain colours instead of a procedural tint.
 */

import { useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useQueries } from '@tanstack/react-query'
import { useState, useEffect, useMemo } from 'react'
import * as THREE from 'three'
import { api } from '../api/client'
import StellarSystemViewer from '../viewers/StellarSystemViewer'
import BranchSelector from '../components/BranchSelector'
import { decodePngToFloat32, generatePlanetTexture } from '../viewers/map/utils/imageCodec'

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

  // --- Stellar system data ---

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

  // --- Planet terrain textures (Route C) ---

  // 1. Which planets have map data?
  const { data: mapPlanetIds } = useQuery({
    queryKey: ['mapPlanets', worldName, selectedBranch],
    queryFn: () => api.listMapPlanets(worldName!, selectedBranch),
    enabled: !!worldName,
    retry: false,
  })

  // 2. Batch-load map metadata for each planet that has a map
  const metaQueries = useQueries({
    queries: (mapPlanetIds ?? []).map((pid) => ({
      queryKey: ['mapMeta', worldName, pid, selectedBranch] as const,
      queryFn: () => api.getMapMeta(worldName!, pid, selectedBranch),
      enabled: !!worldName && !!mapPlanetIds,
      retry: false,
    })),
  })

  // 3. Batch-load elevation PNG blobs
  const elevQueries = useQueries({
    queries: (mapPlanetIds ?? []).map((pid) => ({
      queryKey: ['elevationBlob', worldName, pid, selectedBranch] as const,
      queryFn: () => api.getElevationBlob(worldName!, pid, selectedBranch),
      enabled: !!worldName && !!mapPlanetIds,
      retry: false,
    })),
  })

  // 4. Async: decode each loaded PNG blob → Float32Array, then store
  const [elevData, setElevData] = useState<Map<string, Float32Array>>(new Map())
  const [elevDataDims, setElevDataDims] = useState<Map<string, { w: number; h: number }>>(new Map())

  useEffect(() => {
    if (!mapPlanetIds) return
    let cancelled = false

    async function load() {
      const dataMap = new Map<string, Float32Array>()
      const dimsMap = new Map<string, { w: number; h: number }>()

      for (let i = 0; i < mapPlanetIds!.length; i++) {
        if (cancelled) return
        const pid = mapPlanetIds![i]
        const blob = elevQueries[i]?.data
        if (!blob) continue
        try {
          const { data, width, height } = await decodePngToFloat32(blob)
          dataMap.set(pid, data)
          dimsMap.set(pid, { w: width, h: height })
        } catch {
          // Skip planets whose elevation PNG can't be decoded
        }
      }

      if (!cancelled) {
        setElevData(dataMap)
        setElevDataDims(dimsMap)
      }
    }

    load()
    return () => { cancelled = true }
  }, [mapPlanetIds, elevQueries])

  // 5. Generate DataTextures from decoded elevation data + metadata
  const planetTextures = useMemo(() => {
    const map = new Map<string, THREE.Texture>()
    if (!mapPlanetIds) return map

    for (let i = 0; i < mapPlanetIds.length; i++) {
      const pid = mapPlanetIds[i]
      const meta = metaQueries[i]?.data
      const elev = elevData.get(pid)
      const dims = elevDataDims.get(pid)
      if (!meta || !elev || !dims) continue

      const tex = generatePlanetTexture(
        elev, dims.w, dims.h,
        meta.elevation_min_m ?? -11000,
        meta.elevation_max_m ?? 9000,
        meta.sea_level_m ?? 0,
      )
      map.set(pid, tex)
    }
    return map
  }, [mapPlanetIds, metaQueries, elevData, elevDataDims])

  // --- Render ---

  const isLoading = loadingStellar || loadingPlanets

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
            planetTextures={planetTextures}
          />
        )}
      </div>
    </div>
  )
}
