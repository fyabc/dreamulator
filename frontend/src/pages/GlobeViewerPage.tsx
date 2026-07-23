/**
 * GlobeViewerPage — 3D 球面地形可视化.
 *
 * Route: /worlds/:worldName/globe/:planetId
 *
 * Shares cell interaction, colour modes, sidebar panels, and status bar
 * with the 2D MapViewer.  Layout mirrors MapViewerPage:
 *   left panel (layers) · centre (globe) · right panel (inspector)
 */

import { useParams, useSearchParams, Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useState, useEffect, useMemo, useCallback } from 'react'
import * as THREE from 'three'
import { api } from '../api/client'
import GlobeViewer, { type GlobeVertex, type GlobeRegion } from '../viewers/GlobeViewer'
import BranchSelector from '../components/BranchSelector'
import MapStatusBar from '../components/map/MapStatusBar'
import MapLayerPanel, { type LayerState } from '../components/map/MapLayerPanel'
import MapCellInspector from '../components/map/MapCellInspector'
import useGPUTerrain from '../viewers/map/useGPUTerrain'
import useCellIdMap from '../viewers/map/useCellIdMap'
import { decodePngToFloat32 } from '../viewers/map/utils/imageCodec'
import { normalisedToMeters } from '../viewers/map/utils/projection'
import { buildCellKDTree, type KDTree3D } from '../components/map/utils/kdtree'
import type { VoronoiCell } from '../viewers/map/types'
import type { CursorInfo } from '../components/map/MapViewer'

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

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

  // --- UI State ---
  const [layerState, setLayerState] = useState<LayerState>({ colorMode: 'terrain' })
  const [cursor, setCursor] = useState<CursorInfo | null>(null)
  const [hoveredCellId, setHoveredCellId] = useState<number | null>(null)
  const [selectedCells, setSelectedCells] = useState<Set<number>>(new Set())

  // --- Data ---
  const { data: meta } = useQuery({
    queryKey: ['mapMeta', worldName, planetId, selectedBranch],
    queryFn: () => api.getMapMeta(worldName!, planetId!, selectedBranch),
    enabled: !!worldName && !!planetId,
  })

  const elevMin = meta?.elevation_min_m ?? -11000
  const elevMax = meta?.elevation_max_m ?? 9000
  const seaLevel = meta?.sea_level_m ?? 0

  const { data: elevationBlob } = useQuery({
    queryKey: ['elevationBlob', worldName, planetId, selectedBranch],
    queryFn: () => api.getElevationBlob(worldName!, planetId!, selectedBranch),
    enabled: !!worldName && !!planetId, retry: false,
  })

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

  // CVT mesh (for plates/boundaries modes + cell lookup)
  const { data: cvtMesh } = useQuery({
    queryKey: ['cvtMesh', worldName, planetId, selectedBranch],
    queryFn: () => api.getCvtMesh(worldName!, planetId!, selectedBranch),
    enabled: !!worldName && !!planetId, retry: false,
  })

  const { data: plates } = useQuery({
    queryKey: ['plates', worldName, planetId, selectedBranch],
    queryFn: () => api.getPlates(worldName!, planetId!, selectedBranch),
    enabled: !!worldName && !!planetId, retry: false,
  })

  const cellIdMap = useCellIdMap({
    cvtMesh: cvtMesh ?? null,
    width: meta?.width ?? 2048,
    height: meta?.height ?? 1024,
  })

  // --- GPU texture ---
  const terrainMaterial = useGPUTerrain({
    elevation: elevData,
    width: elevDims.w, height: elevDims.h,
    seaLevel, elevMinM: elevMin, elevMaxM: elevMax,
    colorMode: layerState.colorMode,
    cvtMesh: cvtMesh ?? null,
    cellIdMap: cellIdMap ?? null,
  })

  const terrainTexture = useMemo(() => {
    if (!terrainMaterial) return null
    return (terrainMaterial.uniforms.u_colorMap?.value as THREE.Texture) ?? null
  }, [terrainMaterial])

  // --- KD-tree ---
  const kdTree = useMemo<KDTree3D | null>(() => {
    const cells = cvtMesh?.cells
    if (!cells || cells.length === 0) return null
    return buildCellKDTree(cells as VoronoiCell[])
  }, [cvtMesh])

  const voronoiCells: VoronoiCell[] = useMemo(
    () => (cvtMesh?.cells as VoronoiCell[]) ?? [],
    [cvtMesh],
  )

  const hoveredCellData = useMemo(() => {
    if (hoveredCellId === null) return null
    return voronoiCells.find((c) => c.id === hoveredCellId) ?? null
  }, [voronoiCells, hoveredCellId])

  const hoveredPlate = useMemo(() => {
    if (!hoveredCellData?.plate_id) return null
    return ((plates as any[]) ?? []).find((p) => p.id === hoveredCellData.plate_id) ?? null
  }, [plates, hoveredCellData])

  // --- CVT mesh data for polygon highlights ---
  const globeVertices = useMemo<GlobeVertex[] | undefined>(() => cvtMesh?.vertices, [cvtMesh])
  const globeRegions = useMemo<GlobeRegion[] | undefined>(() => cvtMesh?.regions, [cvtMesh])

  // --- Handlers ---

  const handleCellHover = useCallback((lon: number, lat: number) => {
    const mapW = meta?.width ?? 2048
    const mapH = meta?.height ?? 1024
    const px = Math.round(((lon + 180) / 360) * (mapW - 1))
    const py = Math.round(((90 - lat) / 180) * (mapH - 1))
    const elev = elevData
      ? (elevData?.[Math.max(0, Math.min(mapH - 1, py)) * mapW + Math.max(0, Math.min(mapW - 1, px))] ?? 0)
      : 0

    setCursor({
      lon: Math.round(lon * 100) / 100,
      lat: Math.round(lat * 100) / 100,
      elevation: elev,
      elevationM: normalisedToMeters(elev, elevMin, elevMax),
      pixelX: px,
      pixelY: py,
    })

    if (kdTree) {
      const rad = THREE.MathUtils.degToRad(lat)
      const cosLat = Math.cos(rad)
      const cellId = kdTree.nearest(
        cosLat * Math.cos(THREE.MathUtils.degToRad(lon)),
        Math.sin(rad),
        cosLat * Math.sin(THREE.MathUtils.degToRad(lon)),
      )
      setHoveredCellId(cellId >= 0 ? cellId : null)
    } else {
      setHoveredCellId(null)
    }
  }, [elevData, meta, elevMin, elevMax, kdTree])

  const handleCellClick = useCallback((lon: number, lat: number, ctrlKey: boolean) => {
    if (!kdTree) return
    const rad = THREE.MathUtils.degToRad(lat)
    const cosLat = Math.cos(rad)
    const cellId = kdTree.nearest(
      cosLat * Math.cos(THREE.MathUtils.degToRad(lon)),
      Math.sin(rad),
      cosLat * Math.sin(THREE.MathUtils.degToRad(lon)),
    )
    if (cellId < 0) return
    setSelectedCells((prev) => {
      if (ctrlKey) {
        // Ctrl+double-click → toggle
        const next = new Set(prev)
        if (prev.has(cellId)) next.delete(cellId)
        else next.add(cellId)
        return next
      }
      // Plain double-click → replace
      return new Set([cellId])
    })
  }, [kdTree])

  // --- URLs ---
  const branchQS = selectedBranch ? `?branch=${encodeURIComponent(selectedBranch)}` : ''
  const stellarQS = `${branchQS}${branchQS ? '&' : '?'}focus=${encodeURIComponent(planetId!)}`
  const handleTransition = useCallback(() => {
    navigate(`/worlds/${worldName}/viewer3d${stellarQS}`)
  }, [navigate, worldName, stellarQS])

  // --- Render ---
  if (!worldName || !planetId) {
    return <div className="flex items-center justify-center h-full text-gray-500">未选择世界或行星</div>
  }

  return (
    <div className="flex flex-col h-[calc(100vh-56px)]">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 py-2 bg-space-panel border-b border-space-border shrink-0">
        <Link to={`/worlds/${worldName}`}
          className="text-gray-400 hover:text-neon-cyan transition-colors text-sm">← 返回</Link>
        <h1 className="text-lg font-bold text-neon-cyan neon-glow-subtle">3D 球面视图</h1>
        <span className="text-xs text-gray-600 font-mono">{planetId}</span>
        <div className="flex-1" />
        <Link to={`/worlds/${worldName}/map/${planetId}${branchQS}`}
          className="px-3 py-1 text-sm rounded-lg bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors">
          🗺️ 2D 地图
        </Link>
        <Link to={`/worlds/${worldName}/viewer3d${stellarQS}`}
          className="px-3 py-1 text-sm rounded-lg bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors">
          🔭 恒星系
        </Link>
        <BranchSelector worldName={worldName} selectedBranch={selectedBranch} onSelect={setSelectedBranch} />
      </div>

      {/* Main content — three-panel layout (mirrors MapViewerPage) */}
      <div className="flex flex-1 min-h-0">
        {/* Left panel: layers */}
        <div className="w-56 shrink-0 bg-space-panel/50 border-r border-space-border overflow-y-auto p-3">
          <MapLayerPanel state={layerState} onChange={setLayerState} />
        </div>

        {/* Centre: globe */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 min-h-0 relative">
            <GlobeViewer
              texture={terrainTexture}
              onTransition={handleTransition}
              onCellHover={handleCellHover}
              onCellClick={handleCellClick}
              vertices={globeVertices}
              regions={globeRegions}
              hoveredCellId={hoveredCellId}
              selectedCellIds={selectedCells}
            />
          </div>
          <MapStatusBar cursor={cursor} zoom={1} hoveredCell={hoveredCellData} />
        </div>

        {/* Right panel: cell inspector */}
        <div className="w-52 shrink-0 bg-space-panel/50 border-l border-space-border overflow-y-auto p-3">
          <MapCellInspector
            cell={hoveredCellData}
            plate={hoveredPlate}
            cvtMesh={cvtMesh ?? null}
            planetName={planetId}
          />
        </div>
      </div>
    </div>
  )
}
