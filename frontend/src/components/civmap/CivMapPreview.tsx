/**
 * CivMapPreview — read-only embedded map preview for the civilization tab.
 *
 * Shows a compact Leaflet map with current territory assignments,
 * plus stats and a link to the full editor.
 *
 * Always renders (provides navigation to the editor), shows loading state
 * while data is being fetched.
 */

import { useEffect, useRef, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type {
  CivCountry,
  GeoBoundaryCollection,
  TerritoryAssignment,
} from './types'
import * as api from '../../api/civmapClient'
import { isStaticMode } from '../../api/mode'
import { staticApi } from '../../api/staticClient'

interface CivMapPreviewProps {
  worldName: string
  branch: string | null
}

export default function CivMapPreview({ worldName, branch }: CivMapPreviewProps) {
  const mapRef = useRef<HTMLDivElement>(null)
  const leafletMapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.GeoJSON | null>(null)
  const staticMode = isStaticMode()
  const [mapError, setMapError] = useState<string | null>(null)

  // Fetch territory data
  const { data: territory } = useQuery({
    queryKey: ['civmap', 'territory', worldName, branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivTerritory(worldName, branch) as Promise<any>
        : api.getTerritory(worldName, branch),
    enabled: !!worldName,
  })

  // Fetch ADM1 GeoJSON
  const { data: adm1Geojson, isLoading: adm1Loading } = useQuery({
    queryKey: ['civmap', 'boundaries', worldName, 'adm1', branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivBoundaries(worldName, 'adm1')
        : api.getBoundaries(worldName, 'adm1', branch),
    enabled: !!worldName,
    retry: 2,
    retryDelay: 1000,
  })

  // Fetch ADM0 GeoJSON (borders)
  const { data: adm0Geojson, isLoading: adm0Loading } = useQuery({
    queryKey: ['civmap', 'boundaries', worldName, 'adm0', branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivBoundaries(worldName, 'adm0')
        : api.getBoundaries(worldName, 'adm0', branch),
    enabled: !!worldName,
    retry: 2,
    retryDelay: 1000,
  })

  const countries: CivCountry[] = territory?.countries || []
  const activeSnapshotId: string | null = territory?.active_snapshot || null
  const assignments: TerritoryAssignment[] =
    activeSnapshotId && territory?.assignments?.[activeSnapshotId]
      ? territory.assignments[activeSnapshotId]
      : []

  // Build assignment map
  const assignmentMap = useMemo(() => {
    const m = new Map<string, string>()
    for (const a of assignments) m.set(a.province_id, a.country_id)
    return m
  }, [assignments])

  const countryMap = useMemo(() => {
    const m = new Map<string, CivCountry>()
    for (const c of countries) m.set(c.id, c)
    return m
  }, [countries])

  // Count painted provinces per country
  const paintCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const a of assignments) {
      counts.set(a.country_id, (counts.get(a.country_id) || 0) + 1)
    }
    return counts
  }, [assignments])

  const dataLoading = adm1Loading || adm0Loading
  const hasGeoJson = adm1Geojson?.features?.length > 0

  // Initialize mini map
  useEffect(() => {
    if (!mapRef.current || leafletMapRef.current) return

    try {
      const map = L.map(mapRef.current, {
        center: [35, 25],
        zoom: 3,
        zoomControl: false,
        attributionControl: false,
        preferCanvas: true,
        dragging: true,
        scrollWheelZoom: false,
        doubleClickZoom: false,
      })

      L.tileLayer(
        'https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png',
        { subdomains: 'abcd', maxZoom: 8 },
      ).addTo(map)

      leafletMapRef.current = map
    } catch (err) {
      setMapError(`Leaflet initialization failed: ${err}`)
    }

    return () => {
      if (leafletMapRef.current) {
        leafletMapRef.current.remove()
        leafletMapRef.current = null
      }
    }
  }, [])

  // Update layers when GeoJSON data loads
  useEffect(() => {
    const map = leafletMapRef.current
    if (!map || !hasGeoJson) return

    setMapError(null)

    if (layerRef.current) {
      map.removeLayer(layerRef.current)
      layerRef.current = null
    }

    try {
      const adm1Layer = L.geoJSON(adm1Geojson as GeoBoundaryCollection, {
        style: (feature) => {
          if (!feature) return {}
          const id = (feature.id as string) || ''
          const cid = assignmentMap.get(id)
          const c = cid ? countryMap.get(cid) : undefined
          return {
            fillColor: c?.color || '#333',
            fillOpacity: c ? 0.7 : 0.2,
            color: '#444',
            weight: 0.3,
            opacity: 0.5,
          }
        },
        interactive: false,
      }).addTo(map)

      // Add ADM0 borders on top
      if (adm0Geojson?.features?.length) {
        const adm0Layer = L.geoJSON(adm0Geojson as GeoBoundaryCollection, {
          style: () => ({
            fillColor: 'transparent',
            fillOpacity: 0,
            color: '#888',
            weight: 1,
            opacity: 0.7,
          }),
          interactive: false,
        }).addTo(map)

        const group = L.featureGroup([adm1Layer, adm0Layer])
        layerRef.current = group as any
      } else {
        layerRef.current = adm1Layer
      }
    } catch (err) {
      setMapError(`Failed to render map: ${err}`)
    }
  }, [adm1Geojson, adm0Geojson, assignmentMap, countryMap, hasGeoJson])

  return (
    <div className="glass-panel p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold text-neon-cyan neon-glow-subtle">
          🏛️ 文明地图
        </h2>
        <div className="flex gap-2">
          {!staticMode && (
            <Link
              to={`/worlds/${worldName}/civmap${branch ? `/${branch}` : ''}`}
              className="px-3 py-1.5 rounded-lg text-sm font-medium bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 transition-colors"
            >
              编辑地图 →
            </Link>
          )}
          <Link
            to={`/worlds/${worldName}/civmap${branch ? `/${branch}` : ''}`}
            className="px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-gray-200 transition-colors"
          >
            全屏查看
          </Link>
        </div>
      </div>

      {/* Mini map */}
      <div
        ref={mapRef}
        className="w-full rounded-lg overflow-hidden border border-space-border relative"
        style={{ height: '360px', background: '#1a1a2e' }}
      >
        {dataLoading && !hasGeoJson && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/40 z-[1000]">
            <div className="text-white text-sm">
              {staticMode ? '正在下载地图数据 (33MB)...' : '加载地图中...'}
            </div>
          </div>
        )}
        {mapError && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/40 z-[1000]">
            <div className="text-yellow-300 text-sm px-4 text-center">
              ⚠️ {mapError}
            </div>
          </div>
        )}
      </div>

      {/* Country legend + stats */}
      {countries.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-3">
          {countries.map((c) => (
            <div key={c.id} className="flex items-center gap-2 text-sm">
              <span
                className="w-3 h-3 rounded shrink-0"
                style={{ backgroundColor: c.color }}
              />
              <span className="text-gray-300">{c.name}</span>
              <span className="text-gray-600 text-xs">
                ({paintCounts.get(c.id) || 0} 省)
              </span>
            </div>
          ))}
          {assignments.length === 0 && (
            <span className="text-sm text-gray-500">
              尚未涂色 — {staticMode ? '请在 API 模式下编辑' : '点击「编辑地图」开始'}
            </span>
          )}
        </div>
      )}

      {countries.length === 0 && !staticMode && (
        <p className="mt-3 text-sm text-gray-500">
          尚无架空国家 —{' '}
          <Link
            to={`/worlds/${worldName}/civmap${branch ? `/${branch}` : ''}`}
            className="text-neon-cyan hover:underline"
          >
            前往编辑器创建
          </Link>
        </p>
      )}

      {staticMode && (
        <p className="mt-3 text-xs text-gray-600">
          只读模式 — 地图编辑仅在 API 模式下可用
          {dataLoading && ' | 地图数据加载中...'}
        </p>
      )}
    </div>
  )
}
