/**
 * PackMap — Leaflet CRS.Simple viewer for a region pack.
 *
 * The map's coordinate frame is the pack window's centre-origin kilometres
 * (Leaflet "lat" = y north, "lng" = x east — north ends up at the top for
 * free, matching the PNGs' row 0 = north registration).  The base is the
 * server-rendered topo composite (terrain + lake/sea fills, full-bleed and
 * exactly registered); rivers are drawn as VECTOR polylines grouped into
 * (√-law width class × regime) multipolylines on a canvas renderer — the
 * same symbol semantics as the printed sheet (screen-pixel stroke widths,
 * non-perennial dashes), visible at every zoom and never darkening the
 * underlay the way stacked raster masks would.  Default Leaflet marker
 * icons are avoided (they break under Vite bundling) — labels and the
 * click pin use divIcons and a circleMarker instead.
 */

import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { LonLat } from '../map/utils/mapCoords'
import { graticule, kmToLonLat, lonLatToKm, type PackWindow } from './packCoords'
import type { RiverData } from './types'

interface PackMapProps {
  window: PackWindow
  /** Base image URL, or null while loading (paper placeholder). */
  base: { url: string; opacity?: number } | null
  rivers: RiverData | null
  graticuleOn: boolean
  pin: LonLat | null
  onHover: (ll: LonLat | null) => void
  onProbe: (ll: LonLat) => void
}

const GRATICULE_INK = '#8c7355'
const RIVER_INK = '#2c5c82'

/** Stroke width px: w = 0.5 + 1.5·√(f/f_max), quantised to 0.5 px steps. */
function riverWeight(flow: number, flowMax: number): number {
  const t = flowMax > 0 ? Math.sqrt(Math.max(flow, 0) / flowMax) : 0
  return Math.max(0.5, Math.round((0.5 + 1.5 * t) * 2) / 2)
}

/** Non-perennial dash (px) — the carto pattern scaled for the screen. */
const RIVER_DASH = '8 1.6 1.2 1.6 1.2 1.6'

function boundsOf(w: PackWindow): L.LatLngBounds {
  return L.latLngBounds(
    [-w.extentKmY / 2, -w.extentKmX / 2],
    [w.extentKmY / 2, w.extentKmX / 2],
  )
}

function degreeLabel(value: number, isLat: boolean): string {
  const hemi = isLat ? (value >= 0 ? 'N' : 'S') : value >= 0 ? 'E' : 'W'
  return `${Math.abs(value)}°${hemi}`
}

const LABEL_STYLE =
  'font: 10px/1.4 ui-monospace, monospace; color: #8c7355; background: rgba(248,244,233,0.75);' +
  'padding: 0 3px; border-radius: 2px; white-space: nowrap;'

function labelIcon(text: string, anchor: [number, number]): L.DivIcon {
  return L.divIcon({
    className: '',
    html: `<span style="${LABEL_STYLE}">${text}</span>`,
    iconSize: [34, 14],
    iconAnchor: anchor,
  })
}

export default function PackMap({
  window,
  base,
  rivers,
  graticuleOn,
  pin,
  onHover,
  onProbe,
}: PackMapProps) {
  const { t } = useTranslation('map')
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const rendererRef = useRef<L.Canvas | null>(null)
  const baseRef = useRef<L.ImageOverlay | null>(null)
  const riversRef = useRef<L.LayerGroup | null>(null)
  const graticuleRef = useRef<L.LayerGroup | null>(null)
  const pinRef = useRef<L.CircleMarker | null>(null)
  const hoverRef = useRef(onHover)
  const probeRef = useRef(onProbe)
  hoverRef.current = onHover
  probeRef.current = onProbe
  // Base raster load state (the topo composite is ~10 MB and the first render
  // of a pack can take tens of seconds server-side) — a debug-grade badge.
  const [baseLoading, setBaseLoading] = useState(false)

  // Init once (survives StrictMode double-mount via the cleanup).
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    mapRef.current = L.map(containerRef.current, {
      crs: L.CRS.Simple,
      attributionControl: false,
      zoomControl: true,
      maxZoom: 6,
      preferCanvas: true,
    })
    return () => {
      mapRef.current?.remove()
      mapRef.current = null
      rendererRef.current = null
      baseRef.current = null
      riversRef.current = null
      graticuleRef.current = null
      pinRef.current = null
    }
  }, [])

  // Pointer events — rebound whenever the window (pack) changes so the
  // km → degrees conversion always uses the current geometry.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const move = (e: L.LeafletMouseEvent) => hoverRef.current(kmToLonLat(e.latlng.lng, e.latlng.lat, window))
    const click = (e: L.LeafletMouseEvent) => probeRef.current(kmToLonLat(e.latlng.lng, e.latlng.lat, window))
    const leave = () => hoverRef.current(null)
    map.on('mousemove', move)
    map.on('click', click)
    map.on('mouseout', leave)
    return () => {
      map.off('mousemove', move)
      map.off('click', click)
      map.off('mouseout', leave)
    }
  }, [window])

  // Window (pack) change: refit the view and clamp panning.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const bounds = boundsOf(window)
    map.setMaxBounds(bounds.pad(0.5))
    map.fitBounds(bounds)
  }, [window])

  // Base layer.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (baseRef.current) {
      map.removeLayer(baseRef.current)
      baseRef.current = null
    }
    if (base) {
      setBaseLoading(true)
      const overlay = L.imageOverlay(base.url, boundsOf(window), {
        opacity: base.opacity ?? 1,
      })
      overlay.on('load', () => setBaseLoading(false))
      overlay.on('error', () => setBaseLoading(false))
      baseRef.current = overlay
      overlay.addTo(map)
    } else {
      setBaseLoading(false)
    }
  }, [base, window])

  // Vector rivers — one multipolyline per (width class × regime).
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (riversRef.current) {
      map.removeLayer(riversRef.current)
      riversRef.current = null
    }
    if (!rivers || rivers.segs.length === 0) return
    if (!rendererRef.current) {
      rendererRef.current = L.canvas({ padding: 0.3 })
    }
    const groups = new Map<string, L.LatLngExpression[][]>()
    rivers.segs.forEach((seg, i) => {
      const regime = riverRegime(rivers, i)
      const weight = riverWeight(rivers.flows[i] ?? 0, rivers.flowMax)
      const key = `${weight}:${regime}`
      const entry = groups.get(key) ?? []
      entry.push(seg as L.LatLngExpression[])
      groups.set(key, entry)
    })
    const group = L.layerGroup()
    for (const [key, lines] of groups) {
      const [weight, regime] = key.split(':')
      group.addLayer(
        L.polyline(lines, {
          weight: Number(weight),
          color: RIVER_INK,
          opacity: 0.92,
          dashArray: regime === '1' ? RIVER_DASH : undefined,
          renderer: rendererRef.current ?? undefined,
          interactive: false,
        }),
      )
    }
    riversRef.current = group
    group.addTo(map)
  }, [rivers, window])

  // Graticule (same step ladder and ink as the printed carto sheets).
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (graticuleRef.current) {
      map.removeLayer(graticuleRef.current)
      graticuleRef.current = null
    }
    if (!graticuleOn) return
    const g = graticule(window)
    const group = L.layerGroup()
    const x0 = -window.extentKmX / 2
    const x1 = window.extentKmX / 2
    const y0 = -window.extentKmY / 2
    const y1 = window.extentKmY / 2
    for (const lat of g.lats) {
      const y = lonLatToKm({ lon: window.centerLon, lat }, window).y
      group.addLayer(
        L.polyline(
          [
            [y, x0],
            [y, x1],
          ],
          { color: GRATICULE_INK, weight: 0.8, dashArray: '6 4', interactive: false },
        ),
      )
      group.addLayer(
        L.marker([y, x1], {
          interactive: false,
          icon: labelIcon(degreeLabel(lat, true), [-2, 7]),
        }),
      )
    }
    for (const lon of g.lons) {
      const x = lonLatToKm({ lon, lat: window.centerLat }, window).x
      group.addLayer(
        L.polyline(
          [
            [y0, x],
            [y1, x],
          ],
          { color: GRATICULE_INK, weight: 0.8, dashArray: '6 4', interactive: false },
        ),
      )
      group.addLayer(
        L.marker([y0, x], {
          interactive: false,
          icon: labelIcon(degreeLabel(lon, false), [17, 16]),
        }),
      )
    }
    graticuleRef.current = group
    group.addTo(map)
  }, [graticuleOn, window])

  // Click pin.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (pinRef.current) {
      map.removeLayer(pinRef.current)
      pinRef.current = null
    }
    if (pin) {
      const km = lonLatToKm(pin, window)
      pinRef.current = L.circleMarker([km.y, km.x], {
        radius: 6,
        color: '#22d3ee',
        weight: 2,
        fillColor: '#22d3ee',
        fillOpacity: 0.25,
        interactive: false,
      })
      pinRef.current.addTo(map)
    }
  }, [pin, window])

  return (
    <>
      <div ref={containerRef} className="absolute inset-0 cursor-crosshair bg-[#1a1f2b]" />
      {baseLoading && (
        <div className="absolute top-3 left-14 z-[500] pointer-events-none">
          <span className="inline-block animate-pulse bg-space-panel/90 border border-space-border rounded px-2 py-1 text-xs text-neon-cyan font-mono">
            {t('packs.loadingBase')}
          </span>
        </div>
      )}
    </>
  )
}

/** Regime accessor — legacy packs without a regime channel read as perennial. */
function riverRegime(rivers: RiverData, i: number): number {
  return rivers.regimes[i] ?? 0
}
