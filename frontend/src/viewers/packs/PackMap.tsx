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
import AtlasIcon from '../../components/AtlasIcon'
import type { LonLat } from '../map/utils/mapCoords'
import { kmToLonLat, lonLatToKm, regionFrameZooms, type PackWindow } from './packCoords'
import { projectedRegionGraticule } from './regionGraticule'
import type { RiverData } from './types'
import type { RegionContext } from './useRegionContext'

interface PackMapProps {
  window: PackWindow
  /** Base image URL, or null while loading. */
  base: { url: string; opacity?: number; pixelated?: boolean } | null
  context?: RegionContext | null
  loading?: boolean
  rivers: RiverData | null
  riverOpacity?: number
  graticuleOpacity: number
  pin: LonLat | null
  onHover: (ll: LonLat | null) => void
  onLockPoint: (ll: LonLat) => void
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
  return `${Number(Math.abs(value).toFixed(2))}°${hemi}`
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
  context,
  loading,
  rivers,
  riverOpacity = 1,
  graticuleOpacity,
  pin,
  onHover,
  onLockPoint,
}: PackMapProps) {
  const { t } = useTranslation('map')
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const rendererRef = useRef<L.Canvas | null>(null)
  const baseRef = useRef<L.ImageOverlay | null>(null)
  const riversRef = useRef<L.LayerGroup | null>(null)
  const graticuleRef = useRef<L.LayerGroup | null>(null)
  const pinRef = useRef<L.CircleMarker | null>(null)
  const framingRef = useRef<{ window: PackWindow; mode: 'default' | 'fit' | 'custom' } | null>(null)
  const changeFrame = useRef<((showFullArea: boolean) => void) | null>(null)
  const hoverRef = useRef(onHover)
  const lockRef = useRef(onLockPoint)
  hoverRef.current = onHover
  lockRef.current = onLockPoint
  // Base raster load state (the topo composite is ~10 MB and the first render
  // of a pack can take tens of seconds server-side) — a debug-grade badge.
  const [baseLoading, setBaseLoading] = useState(false)
  const [fullArea, setFullArea] = useState(false)

  // Init once (survives StrictMode double-mount via the cleanup).
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return
    mapRef.current = L.map(containerRef.current, {
      crs: L.CRS.Simple,
      attributionControl: false,
      zoomControl: false,
      doubleClickZoom: false,
      maxZoom: 6,
      maxBoundsViscosity: 1,
      zoomSnap: 0,
      zoomDelta: 0.5,
      preferCanvas: true,
    })
    mapRef.current.createPane('region-context').style.zIndex = '200'
    mapRef.current.createPane('region-boundary').style.zIndex = '410'
    const grid = mapRef.current.createPane('region-graticule')
    grid.style.zIndex = '405'
    grid.style.pointerEvents = 'none'
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
    const bounds = boundsOf(window)
    const container = map.getContainer()
    let frame = 0
    let pending: L.LatLng | null = null
    let touch = false
    const point = (latlng: L.LatLng) => bounds.contains(latlng) ? kmToLonLat(latlng.lng, latlng.lat, window) : null
    const move = (event: PointerEvent) => {
      if (event.pointerType === 'touch' || event.buttons) return
      pending = event.target instanceof Element && event.target.closest('.leaflet-control') ? null : map.mouseEventToLatLng(event)
      if (!frame) frame = requestAnimationFrame(() => {
        frame = 0
        hoverRef.current(pending ? point(pending) : null)
      })
    }
    const lock = (event: L.LeafletMouseEvent) => {
      const location = point(event.latlng)
      if (location) lockRef.current(location)
    }
    const pointerDown = (event: PointerEvent) => { touch = event.pointerType === 'touch' || event.pointerType === 'pen' }
    const click = (event: L.LeafletMouseEvent) => { if (touch) lock(event) }
    const leave = () => {
      pending = null
      cancelAnimationFrame(frame)
      frame = 0
      hoverRef.current(null)
    }
    container.addEventListener('pointerdown', pointerDown)
    container.addEventListener('pointermove', move, true)
    container.addEventListener('pointerleave', leave)
    map.on('click', click)
    map.on('dblclick', lock)
    return () => {
      cancelAnimationFrame(frame)
      container.removeEventListener('pointerdown', pointerDown)
      container.removeEventListener('pointermove', move, true)
      container.removeEventListener('pointerleave', leave)
      map.off('click', click)
      map.off('dblclick', lock)
    }
  }, [window])

  const contextWindow = context?.window
  const frameAction = contextWindow ? 'context' : fullArea ? 'fill' : 'fit'
  useEffect(() => {
    const map = mapRef.current
    const container = containerRef.current
    if (!map || !container) return
    const bounds = boundsOf(window)
    if (framingRef.current?.window !== window) framingRef.current = { window, mode: 'default' }
    const framing = framingRef.current
    let applyingFrame = false
    const applyFrame = () => {
      const { clientWidth, clientHeight } = container
      if (!clientWidth || !clientHeight) return
      const zooms = regionFrameZooms(window, clientWidth, clientHeight)
      const contextZoom = contextWindow ? zooms.fit - 0.5 : zooms.fill
      applyingFrame = true
      map.invalidateSize({ animate: false })
      map.setMaxZoom(Math.max(6, Math.ceil(zooms.fill) + 2))
      map.setMinZoom(contextWindow ? Math.min(contextZoom, regionFrameZooms(contextWindow, clientWidth, clientHeight).fill) : zooms.fit)
      if (framing.mode !== 'custom') map.setView(bounds.getCenter(), framing.mode === 'fit' ? zooms.fit : contextZoom, { animate: false })
      applyingFrame = false
    }
    const useCustomFrame = () => { if (!applyingFrame) framing.mode = 'custom' }
    map.setMaxBounds(contextWindow ? boundsOf(contextWindow) : bounds)
    applyFrame()
    changeFrame.current = (showFullArea) => {
      framing.mode = showFullArea ? 'fit' : 'default'
      applyFrame()
      setFullArea(showFullArea)
    }
    setFullArea(framing.mode === 'fit')
    map.on('dragstart zoomstart', useCustomFrame)
    const resize = new ResizeObserver(applyFrame)
    resize.observe(container)
    return () => {
      map.off('dragstart zoomstart', useCustomFrame)
      resize.disconnect()
      changeFrame.current = null
    }
  }, [window, contextWindow])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !context) return
    const bounds = boundsOf(window)
    const group = L.layerGroup([
      L.imageOverlay(context.url, boundsOf(context.window), { pane: 'region-context', interactive: false, zIndex: 0 }),
      L.rectangle(bounds, { pane: 'region-boundary', color: '#071521', weight: 3, fill: false, interactive: false }),
      L.rectangle(bounds, { pane: 'region-boundary', color: '#e2f5ff', weight: 1.5, dashArray: '6 5', fill: false, interactive: false }),
    ]).addTo(map)
    return () => { group.remove() }
  }, [context, window])

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
        className: base.pixelated ? 'atlas-region-field' : undefined,
      })
      overlay.setZIndex(-1)
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
          opacity: 0.92 * riverOpacity,
          dashArray: regime === '1' ? RIVER_DASH : undefined,
          renderer: rendererRef.current ?? undefined,
          interactive: false,
        }),
      )
    }
    riversRef.current = group
    group.addTo(map)
  }, [rivers, riverOpacity, window])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (graticuleRef.current) {
      map.removeLayer(graticuleRef.current)
      graticuleRef.current = null
    }
    const group = L.layerGroup()
    for (const { paths, coordinate, latitude } of projectedRegionGraticule(contextWindow ?? window)) {
      const lines = paths.map(path => path.map(([x, y]) => L.latLng(y, x)))
      group.addLayer(L.polyline(lines, { pane: 'region-graticule', color: GRATICULE_INK, weight: 1,
        interactive: false }))
      const lastLine = lines[lines.length - 1]
      const anchor = latitude ? lastLine[lastLine.length - 1] : lines[0][0]
      if (anchor) group.addLayer(L.marker(anchor, { pane: 'region-graticule', interactive: false,
        icon: labelIcon(degreeLabel(coordinate, latitude), latitude ? [28, 7] : [17, 16]) }))
    }
    graticuleRef.current = group
    group.addTo(map)
  }, [contextWindow, window])

  useEffect(() => {
    const pane = mapRef.current?.getPane('region-graticule')
    if (pane) pane.style.opacity = String(graticuleOpacity)
  }, [graticuleOpacity])

  // Locked point.
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
      <div ref={containerRef} className="absolute inset-0 cursor-crosshair !bg-space-bg" />
      {base && <button type="button" onClick={() => changeFrame.current?.(frameAction === 'fit')}
        className="atlas-tool-button absolute right-3 top-3 z-[500] min-h-11 text-xs lg:min-h-8"
        title={t(`packs.frame.${frameAction}Hint`)}>
        <AtlasIcon name="frame" className="size-4" /> {t(`packs.frame.${frameAction}`)}
      </button>}
      {context && <div className="pointer-events-none absolute bottom-3 left-3 z-[500] flex max-w-[92%] items-center gap-2 rounded border border-space-border bg-space-bg/90 px-2 py-1 text-[11px] text-gray-200">
        <span aria-hidden="true" className="w-4 border-t-2 border-dashed border-gray-100" />
        {t(context.currentReference ? 'packs.frame.currentReference' : 'packs.frame.contextReference')}
      </div>}
      {(baseLoading || loading) && (
        <div className="absolute top-3 left-3 z-[500] pointer-events-none">
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
