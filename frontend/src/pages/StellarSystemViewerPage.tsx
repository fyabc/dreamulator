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

import { useParams, useSearchParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useQueries } from '@tanstack/react-query'
import { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import * as THREE from 'three'
import { api } from '../api/client'
import {
  catalogStarToStarData,
  catalogBodyToPlanetData,
  type SystemCatalog,
} from '../api/catalogAdapter'
import StellarSystemViewer from '../viewers/StellarSystemViewer'
import BranchSelector from '../components/BranchSelector'
import { decodePngToFloat32, generatePlanetTexture } from '../viewers/map/utils/imageCodec'
import type { SelectedBody } from '../viewers/InfoPanel'

export default function StellarSystemViewerPage() {
  const { t } = useTranslation('common')
  const { worldName } = useParams<{ worldName: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const selectedBranch = searchParams.get('branch') || null
  const focusPlanetId = searchParams.get('focus') || undefined
  const [selectedBody, setSelectedBody] = useState<SelectedBody>(null)

  const setSelectedBranch = (branch: string | null) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (branch) next.set('branch', branch)
      else next.delete('branch')
      return next
    }, { replace: true })
  }

  // --- Stellar system data ---
  // The system catalog (derived) is the single merged source for stars,
  // orbits and bodies — no client-side merging of stellar.yaml/planets.yaml.

  const {
    data: catalog,
    isLoading: loadingCatalog,
    isError: catalogError,
  } = useQuery<SystemCatalog>({
    queryKey: ['systemCatalog', worldName, selectedBranch],
    queryFn: () => api.getSystemCatalog(worldName!, selectedBranch),
    enabled: !!worldName,
    retry: false,
  })

  const stellarSystem = useMemo(
    () =>
      catalog
        ? {
            stars: (catalog.stars ?? []).map(catalogStarToStarData),
            orbits: catalog.orbits ?? [],
          }
        : null,
    [catalog],
  )

  const planets = useMemo(
    () => (catalog?.bodies ?? []).map(catalogBodyToPlanetData),
    [catalog],
  )

  const { data: habitableZones, isError: hzError } = useQuery({
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

  // 2. Fetch CVT mesh for the selected planet (enables terrain summary in InfoPanel)
  const selectedPlanetId =
    selectedBody?.type === 'planet' ? selectedBody.data.id : null
  const selectedHasMap =
    selectedPlanetId != null && (mapPlanetIds ?? []).includes(selectedPlanetId)
  const { data: selectedPlanetCvtMesh } = useQuery({
    queryKey: ['cvtMesh', worldName, selectedPlanetId, selectedBranch] as const,
    queryFn: () => api.getCvtMesh(worldName!, selectedPlanetId!, selectedBranch),
    enabled: !!worldName && selectedHasMap,
    retry: false,
  })

  // 3. Batch-load map metadata for each planet that has a map
  const metaQueries = useQueries({
    queries: (mapPlanetIds ?? []).map((pid) => ({
      queryKey: ['mapMeta', worldName, pid, selectedBranch] as const,
      queryFn: () => api.getMapMeta(worldName!, pid, selectedBranch),
      enabled: !!worldName && !!mapPlanetIds,
      retry: false,
    })),
  })

  // 4. Batch-load elevation PNG blobs
  const elevQueries = useQueries({
    queries: (mapPlanetIds ?? []).map((pid) => ({
      queryKey: ['elevationBlob', worldName, pid, selectedBranch] as const,
      queryFn: () => api.getElevationBlob(worldName!, pid, selectedBranch),
      enabled: !!worldName && !!mapPlanetIds,
      retry: false,
    })),
  })

  // 5. Async: decode each loaded PNG blob → Float32Array, then store
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

  // 6. Generate DataTextures from decoded elevation data + metadata
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

  const isLoading = loadingCatalog

  if (!worldName) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        {t('status.noWorld')}
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-space-border">
        <Link
          to={`/worlds/${worldName}`}
          className="text-gray-400 hover:text-neon-cyan transition-colors text-sm"
        >
          {t('action.back')}
        </Link>
        <h1 className="text-xl font-semibold text-neon-cyan neon-glow-subtle">
          {t('stellar.title')}
        </h1>

        <div className="flex-1" />

        {/* Planet selector — navigate to globe or focus in stellar view */}
        {planets && planets.length > 0 && (
          <select
            value={focusPlanetId ?? ''}
            onChange={(e) => {
              const pid = e.target.value
              if (!pid) return
              const hasMap = mapPlanetIds?.includes(pid)
              const branchQS = selectedBranch ? `?branch=${encodeURIComponent(selectedBranch)}` : ''
              if (hasMap) {
                // Navigate to globe view for planets with map data
                navigate(`/worlds/${worldName}/globe/${pid}${branchQS}`)
              } else {
                // Focus on the planet in the stellar view
                setSearchParams((prev) => {
                  const next = new URLSearchParams(prev)
                  next.set('focus', pid)
                  return next
                }, { replace: true })
              }
            }}
            className="px-2 py-1 rounded bg-space-surface text-sm text-gray-300 border border-space-border"
          >
            <option value="">{t('stellar.selectPlanet')}</option>
            {planets.map((p: any) => (
              <option key={p.id} value={p.id}>
                {p.name ?? p.id}
                {mapPlanetIds?.includes(p.id) ? ' 🌐' : ''}
              </option>
            ))}
          </select>
        )}

        <BranchSelector
          worldName={worldName}
          selectedBranch={selectedBranch}
          onSelect={setSelectedBranch}
        />
      </div>

      {/* Viewer */}
      <div className="flex-1 relative">
        {catalogError || hzError ? (
          <div className="absolute inset-0 flex items-center justify-center text-gray-400">
            <div className="glass-panel p-6 text-center">
              <p className="text-red-400 font-semibold mb-2">{t('stellar.loadFailed')}</p>
              <p className="text-sm">{t('stellar.loadFailedDetail')}</p>
            </div>
          </div>
        ) : isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center text-gray-500">
            {t('status.loading')}
          </div>
        ) : (
          <StellarSystemViewer
            stellar={stellarSystem}
            planets={planets}
            habitableZones={habitableZones}
            planetTextures={planetTextures}
            worldName={worldName}
            branchQS={selectedBranch ? `?branch=${encodeURIComponent(selectedBranch)}` : ''}
            mapPlanetIds={mapPlanetIds ? new Set(mapPlanetIds) : undefined}
            focusPlanetId={focusPlanetId}
            selectedPlanetCvtMesh={selectedPlanetCvtMesh ?? null}
            onSelectionChange={setSelectedBody}
          />
        )}
      </div>
    </div>
  )
}
