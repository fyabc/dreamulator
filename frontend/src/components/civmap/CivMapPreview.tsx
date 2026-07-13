/**
 * CivMapPreview — embedded map preview for the civilization tab.
 *
 * Shows a compact Leaflet map with territory coloring, country legend,
 * and links to the full editor. Only renders for branches with civmap data.
 */

import { useEffect, useMemo, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type {
  CivCountry,
  GeoBoundaryCollection,
  TerritoryAssignment,
} from './types'
import { geoJsonAreaKm2, formatArea } from './areaUtils'
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
  const layerRef = useRef<L.Layer | null>(null)
  const staticMode = isStaticMode()

  // Fetch territory data (lightweight JSON)
  const { data: territory } = useQuery({
    queryKey: ['civmap', 'territory', worldName, branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivTerritory(worldName, branch) as Promise<any>
        : api.getTerritory(worldName, branch),
    enabled: !!worldName,
  })

  // Fetch ADM1 GeoJSON (for fill layer)
  const { data: adm1Geojson } = useQuery({
    queryKey: ['civmap', 'boundaries', worldName, 'adm1', branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivBoundaries(worldName, 'adm1')
        : api.getBoundaries(worldName, 'adm1', branch),
    enabled: !!worldName,
  })

  // Fetch ADM0 GeoJSON (for border overlay)
  const { data: adm0Geojson } = useQuery({
    queryKey: ['civmap', 'boundaries', worldName, 'adm0', branch],
    queryFn: () =>
      staticMode
        ? staticApi.getCivBoundaries(worldName, 'adm0')
        : api.getBoundaries(worldName, 'adm0', branch),
    enabled: !!worldName,
  })

  const countries: CivCountry[] = territory?.countries || []
  const activeSnapshotId: string | null = territory?.active_snapshot || null
  const assignments: TerritoryAssignment[] =
    activeSnapshotId && territory?.assignments?.[activeSnapshotId]
      ? territory.assignments[activeSnapshotId]
      : []

  // All hooks below this point — no early returns between hooks

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

  // Calculate area (km²) per fictional country from assigned provinces
  const areaCounts = useMemo(() => {
    const areas = new Map<string, number>()
    if (!adm1Geojson?.features) return areas

    // Build feature lookup by ID
    const featureMap = new Map<string, any>()
    for (const f of adm1Geojson.features) {
      if (f.id) featureMap.set(f.id as string, f)
    }

    // Sum area of each assigned province
    for (const a of assignments) {
      const feature = featureMap.get(a.province_id)
      if (feature) {
        const area = geoJsonAreaKm2(feature.geometry)
        areas.set(a.country_id, (areas.get(a.country_id) || 0) + area)
      }
    }
    return areas
  }, [assignments, adm1Geojson])

  const hasCivMapData = countries.length > 0 || (territory?.snapshots?.length ?? 0) > 0
  const hasGeoJson = !!adm1Geojson?.features?.length

  // Initialize Leaflet map (once)
  useEffect(() => {
    if (!mapRef.current || leafletMapRef.current) return
    if (!hasCivMapData) return

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

    return () => {
      map.remove()
      leafletMapRef.current = null
    }
  }, [hasCivMapData])

  // Update GeoJSON layers when data changes
  useEffect(() => {
    const map = leafletMapRef.current
    if (!map || !hasGeoJson) return

    if (layerRef.current) {
      map.removeLayer(layerRef.current)
      layerRef.current = null
    }

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
    })

    const layers: L.Layer[] = [adm1Layer]

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
      })
      layers.push(adm0Layer)
    }

    const group = L.featureGroup(layers)
    group.addTo(map)
    layerRef.current = group
  }, [adm1Geojson, adm0Geojson, assignmentMap, countryMap, hasGeoJson])

  // Early return AFTER all hooks
  if (!hasCivMapData) {
    return null
  }

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
        className="w-full rounded-lg overflow-hidden border border-space-border"
        style={{ height: '360px', background: '#1a1a2e' }}
      />

      {/* Country legend + area */}
      {countries.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-3">
          {countries.map((c) => (
            <div key={c.id} className="flex items-center gap-2 text-sm">
              <span
                className="w-3 h-3 rounded shrink-0"
                style={{ backgroundColor: c.color }}
              />
              <span className="text-gray-300">{c.name}</span>
              {(areaCounts.get(c.id) ?? 0) > 0 && (
                <span className="text-gray-500 text-xs">
                  {formatArea(areaCounts.get(c.id)!)} km²
                </span>
              )}
            </div>
          ))}
          {assignments.length === 0 && (
            <span className="text-sm text-gray-500">
              尚未涂色 — {staticMode ? '请在 API 模式下编辑' : '点击「编辑地图」开始'}
            </span>
          )}
        </div>
      )}

      {staticMode && (
        <p className="mt-3 text-xs text-gray-600">
          只读模式 — 地图编辑仅在 API 模式下可用
        </p>
      )}
    </div>
  )
}
