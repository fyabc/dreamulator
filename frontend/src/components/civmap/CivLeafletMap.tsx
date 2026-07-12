/**
 * CivLeafletMap — Leaflet-based map for rendering GeoJSON admin boundaries
 * with interactive province painting.
 *
 * Architecture:
 * - ADM1 provinces are ALWAYS rendered as the fill layer (individual colors).
 * - ADM0 country borders are overlaid on top when level='adm0'.
 * - Level only affects interaction granularity:
 *   - adm1: click selects a single province
 *   - adm0: click selects all provinces of the country
 */

import { useEffect, useRef, useCallback, useMemo } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type {
  BoundaryLevel,
  CivCountry,
  CountryProvinceMapping,
  GeoBoundaryCollection,
  PaintToolMode,
  ProvinceInfo,
  TerritoryAssignment,
} from './types'

interface CivLeafletMapProps {
  /** ADM1 province GeoJSON — always used as the fill layer */
  adm1Geojson: GeoBoundaryCollection | null
  /** ADM0 country GeoJSON — overlaid as borders when level='adm0' */
  adm0Geojson: GeoBoundaryCollection | null
  level: BoundaryLevel
  countries: CivCountry[]
  assignments: TerritoryAssignment[]
  /** Reverse lookup: province adm1_code → country ISO_A2 */
  provinceCountryMap: Record<string, string>
  countryProvinceMap: CountryProvinceMapping
  toolMode: PaintToolMode
  onProvinceHover: (info: ProvinceInfo | null) => void
  /** Called with province_id (adm1_code). Parent handles ADM0 expansion. */
  onProvincePaint: (provinceId: string) => void
  loading?: boolean
}

/** Build a lookup from province_id → fictional country_id */
function buildAssignmentMap(
  assignments: TerritoryAssignment[],
): Map<string, string> {
  const m = new Map<string, string>()
  for (const a of assignments) {
    m.set(a.province_id, a.country_id)
  }
  return m
}

/** Build a lookup from fictional country_id → CivCountry */
function buildCountryMap(countries: CivCountry[]): Map<string, CivCountry> {
  const m = new Map<string, CivCountry>()
  for (const c of countries) {
    m.set(c.id, c)
  }
  return m
}

/** Extract province info from an ADM1 GeoJSON feature */
function extractProvinceInfo(
  feature: GeoJSON.Feature,
  assignmentMap: Map<string, string>,
  countryMap: Map<string, CivCountry>,
  provinceCountryMap: Record<string, string>,
  countryProvinceMap: CountryProvinceMapping,
  level: BoundaryLevel,
): ProvinceInfo {
  const props = feature.properties || {}
  const id = (feature.id as string) || ''
  const name = (props['name'] as string) || (props['name_en'] as string) || id
  const admin = (props['admin'] as string) || ''
  const type = (props['type_en'] as string) || 'Province'

  const fictionalCountryId = assignmentMap.get(id) || null
  const fictionalCountry = fictionalCountryId ? countryMap.get(fictionalCountryId) || null : null

  // For ADM0 level, also show country-level aggregate info
  const isoA2 = provinceCountryMap[id]
  let provinceCount: number | undefined
  let paintedCount: number | undefined

  if (level === 'adm0' && isoA2) {
    const provinceIds = countryProvinceMap[isoA2] || []
    provinceCount = provinceIds.length
    paintedCount = provinceIds.filter((pid) => assignmentMap.has(pid)).length
  }

  return {
    id,
    name: level === 'adm0' && isoA2 ? admin || name : name,
    admin,
    type: level === 'adm0' ? 'Country' : type,
    country_id: fictionalCountryId,
    country_name: fictionalCountry?.name || null,
    country_color: fictionalCountry?.color || null,
    province_count: provinceCount,
    painted_count: paintedCount,
  }
}

export default function CivLeafletMap({
  adm1Geojson,
  adm0Geojson,
  level,
  countries,
  assignments,
  provinceCountryMap,
  countryProvinceMap,
  toolMode,
  onProvinceHover,
  onProvincePaint,
  loading,
}: CivLeafletMapProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const adm1LayerRef = useRef<L.GeoJSON | null>(null)
  const adm0LayerRef = useRef<L.GeoJSON | null>(null)

  const assignmentMap = useMemo(() => buildAssignmentMap(assignments), [assignments])
  const countryMap = useMemo(() => buildCountryMap(countries), [countries])

  // Initialize map once
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return

    const map = L.map(mapContainerRef.current, {
      center: [35, 25],
      zoom: 4,
      zoomControl: true,
      preferCanvas: true,
      worldCopyJump: true,
    })

    L.tileLayer(
      'https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png',
      {
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> ' +
          '&copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 12,
      },
    ).addTo(map)

    mapRef.current = map

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  // Style for ADM1 province fill layer
  const getAdm1Style = useCallback(
    (feature: GeoJSON.Feature | undefined): L.PathOptions => {
      if (!feature) return {}
      const id = (feature.id as string) || ''
      const fictionalCountryId = assignmentMap.get(id)
      const fc = fictionalCountryId ? countryMap.get(fictionalCountryId) : undefined

      return {
        fillColor: fc?.color || '#333',
        fillOpacity: fc ? 0.7 : 0.3,
        color: level === 'adm0' ? '#444' : '#666',
        weight: level === 'adm0' ? 0.3 : 0.5,
        opacity: 0.6,
      }
    },
    [assignmentMap, countryMap, level],
  )

  // Style for ADM0 country border overlay (no fill, thick borders)
  const adm0BorderStyle: L.PathOptions = {
    fillColor: 'transparent',
    fillOpacity: 0,
    color: '#aaa',
    weight: 1.5,
    opacity: 0.9,
  }

  // Update ADM1 fill layer when data or assignments change
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    if (adm1LayerRef.current) {
      map.removeLayer(adm1LayerRef.current)
      adm1LayerRef.current = null
    }

    if (!adm1Geojson || adm1Geojson.features.length === 0) return

    const layer = L.geoJSON(adm1Geojson, {
      style: getAdm1Style,
      onEachFeature: (feature, featureLayer) => {
        featureLayer.on('mouseover', () => {
          (featureLayer as L.Path).setStyle({ weight: 2, color: '#fff', opacity: 1 })
          const info = extractProvinceInfo(
            feature, assignmentMap, countryMap,
            provinceCountryMap, countryProvinceMap, level,
          )
          onProvinceHover(info)
        })

        featureLayer.on('mouseout', () => {
          adm1LayerRef.current?.resetStyle(featureLayer)
          onProvinceHover(null)
        })

        featureLayer.on('click', () => {
          const id = (feature.id as string) || ''
          onProvincePaint(id)
        })
      },
    }).addTo(map)

    adm1LayerRef.current = layer
  }, [adm1Geojson, getAdm1Style, assignmentMap, countryMap, provinceCountryMap, countryProvinceMap, level, onProvinceHover, onProvincePaint])

  // Update ADM0 border overlay when level or data changes
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    // Remove old ADM0 layer
    if (adm0LayerRef.current) {
      map.removeLayer(adm0LayerRef.current)
      adm0LayerRef.current = null
    }

    // Only add ADM0 borders when at adm0 level
    if (level !== 'adm0' || !adm0Geojson || adm0Geojson.features.length === 0) return

    const layer = L.geoJSON(adm0Geojson, {
      style: () => adm0BorderStyle,
      interactive: false, // Don't intercept mouse events — let ADM1 handle them
    }).addTo(map)

    adm0LayerRef.current = layer
  }, [level, adm0Geojson])

  // Cursor style based on tool mode
  const cursorStyle = useMemo(() => {
    if (toolMode === 'paint') return 'crosshair'
    if (toolMode === 'erase') return 'not-allowed'
    return 'default'
  }, [toolMode])

  return (
    <div className="relative w-full h-full">
      <div
        ref={mapContainerRef}
        className="w-full h-full"
        style={{ cursor: cursorStyle, background: '#1a1a2e' }}
      />
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/50 z-[1000]">
          <div className="text-white text-lg">加载地图数据中...</div>
        </div>
      )}
    </div>
  )
}
