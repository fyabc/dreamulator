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

import { useParams, useSearchParams, Link } from 'react-router-dom'
import { useQuery, useQueries } from '@tanstack/react-query'
import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import * as THREE from 'three'
import { api } from '../api/client'
import {
  catalogStarToStarData,
  catalogBodyToPlanetData,
  type SystemCatalog,
} from '../api/catalogAdapter'
import StellarSystemViewer from '../viewers/StellarSystemViewer'
import AtlasIcon from '../components/AtlasIcon'
import { useCelestialName } from '../i18n/celestialNames'
import { decodePngToFloat32, generatePlanetTexture } from '../viewers/map/utils/imageCodec'
import type { SelectedBody } from '../viewers/InfoPanel'
import type { StellarFocusMode } from '../viewers/utils/stellarCamera'

const actionClass = 'inline-flex min-h-10 items-center justify-center gap-1.5 rounded-md border border-space-border px-2.5 text-sm font-medium text-gray-200 hover:bg-space-surface'
const combineQueryData = <Data,>(results: { data?: Data }[]) => results.map(({ data }) => data)

export default function StellarSystemViewerPage() {
  const { t } = useTranslation('common')
  const { worldName } = useParams<{ worldName: string }>()
  const celestialName = useCelestialName(worldName)
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedBranch = searchParams.get('branch') || null
  const requestedBodyId = searchParams.get('focus')
  const [detailsBodyId, setDetailsBodyId] = useState<string | null>(null)
  const detailsButton = useRef<HTMLButtonElement>(null)
  const [focusRequest, setFocusRequest] = useState<{ id: string; mode: StellarFocusMode; nonce: number } | null>(null)

  const selectBody = useCallback((id: string | null, openDetails = false) => {
    setDetailsBodyId(openDetails ? id : null)
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (id) next.set('focus', id)
      else next.delete('focus')
      return next
    }, { replace: true })
  }, [setSearchParams])

  const handleSelectionChange = useCallback((body: SelectedBody) => {
    selectBody(body?.data.id ?? null, true)
  }, [selectBody])

  const requestFocus = (id: string, mode: StellarFocusMode) => {
    if (mode === 'orbit') setDetailsBodyId(null)
    setFocusRequest((last) => ({ id, mode, nonce: (last?.nonce ?? 0) + 1 }))
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

  const stars = useMemo(() => (catalog?.stars ?? []).map((star) => ({
    ...star, name: celestialName(star.id, star.name),
  })), [catalog, celestialName])
  const bodies = useMemo(() => (catalog?.bodies ?? []).map((body) => ({
    ...body, name: celestialName(body.id, body.name),
  })), [catalog, celestialName])

  const stellarSystem = useMemo(
    () =>
      catalog
        ? {
            stars: stars.map(catalogStarToStarData),
            orbits: catalog.orbits ?? [],
          }
        : null,
    [catalog, stars],
  )

  const planets = useMemo(
    () => bodies.map(catalogBodyToPlanetData),
    [bodies],
  )
  const selectedPlanet = planets.find((planet) => planet.id === requestedBodyId)
  const selectedStar = stellarSystem?.stars.find((star) => star.id === requestedBodyId)
  const focusBodyId = selectedPlanet?.id ?? selectedStar?.id
  const hasOrbit = stellarSystem?.orbits.some((orbit) => orbit.body_id === focusBodyId && orbit.semi_major_axis_au > 0)
  const hasBodyRadius = (selectedPlanet?.radius ?? selectedStar?.derived?.computed_radius ?? selectedStar?.radius ?? 0) > 0
  const detailsOpen = !!focusBodyId && focusBodyId === detailsBodyId

  // Catalog lookups for the InfoPanel's rich field groups (orbit elements,
  // derived thermal/season fields, atmosphere composition, star age/HZ).
  const bodyCatalog = useMemo(
    () => new Map(bodies.map((body) => [body.id, body])),
    [bodies],
  )
  const starCatalog = useMemo(
    () => new Map(stars.map((star) => [star.id, star])),
    [stars],
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
  const selectedPlanetId = selectedPlanet?.id
  const mapPath = selectedPlanetId && mapPlanetIds?.includes(selectedPlanetId) ? encodeURIComponent(selectedPlanetId) : null
  const branchQuery = selectedBranch ? `?${new URLSearchParams({ branch: selectedBranch })}` : ''
  const worldPath = `/worlds/${encodeURIComponent(worldName ?? '')}`
  const { data: selectedPlanetCvtMesh } = useQuery({
    queryKey: ['cvtMesh', worldName, selectedPlanetId, selectedBranch] as const,
    queryFn: () => api.getCvtMesh(worldName!, selectedPlanetId!, selectedBranch),
    enabled: !!worldName && !!mapPath && detailsOpen,
    retry: false,
  })

  // 3. Batch-load map metadata for each planet that has a map
  const mapMeta = useQueries({
    queries: (mapPlanetIds ?? []).map((pid) => ({
      queryKey: ['mapMeta', worldName, pid, selectedBranch] as const,
      queryFn: () => api.getMapMeta(worldName!, pid, selectedBranch),
      enabled: !!worldName && !!mapPlanetIds,
      retry: false,
    })),
    combine: combineQueryData,
  })

  // 4. Batch-load elevation PNG blobs
  const elevationBlobs = useQueries({
    queries: (mapPlanetIds ?? []).map((pid) => ({
      queryKey: ['elevationBlob', worldName, pid, selectedBranch] as const,
      queryFn: () => api.getElevationBlob(worldName!, pid, selectedBranch),
      enabled: !!worldName && !!mapPlanetIds,
      retry: false,
    })),
    combine: combineQueryData,
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
        const blob = elevationBlobs[i]
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
  }, [mapPlanetIds, elevationBlobs])

  // 6. Generate DataTextures from decoded elevation data + metadata
  // Waterless bodies (no hydrosphere / ~zero water coverage — Mars, Moon,
  // Venus, Titan) use the arid land ramp: below-datum lows are dark basins,
  // never ocean blue.  Water worlds (Earth, nacrea) keep the ETOPO scheme.
  const waterlessIds = useMemo(() => {
    const ids = new Set<string>()
    for (const body of catalog?.bodies ?? []) {
      const coverage = body.hydrosphere?.water_coverage
      if (coverage == null || coverage < 0.005) ids.add(body.id)
    }
    return ids
  }, [catalog])

  const planetTextures = useMemo(() => {
    const map = new Map<string, THREE.Texture>()
    if (!mapPlanetIds) return map

    for (let i = 0; i < mapPlanetIds.length; i++) {
      const pid = mapPlanetIds[i]
      const meta = mapMeta[i]
      const elev = elevData.get(pid)
      const dims = elevDataDims.get(pid)
      if (!meta || !elev || !dims) continue

      const tex = generatePlanetTexture(
        elev, dims.w, dims.h,
        meta.elevation_min_m ?? -11000,
        meta.elevation_max_m ?? 9000,
        meta.sea_level_m ?? 0,
        256,
        waterlessIds.has(pid),
      )
      map.set(pid, tex)
    }
    return map
  }, [mapPlanetIds, mapMeta, elevData, elevDataDims, waterlessIds])

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
    <div className="atlas-system-workspace flex flex-col">
      <header className="space-y-2 border-b border-space-border bg-space-bg px-3 py-2 sm:px-5 sm:py-3">
        <div className="flex flex-wrap items-center justify-between gap-x-5 gap-y-2">
          <div className="flex min-w-0 items-center gap-2.5">
            <Link to={`${worldPath}${branchQuery}`} aria-label={t('stellar.backToWorld')}
              title={t('stellar.backToWorld')} className={`${actionClass} size-10 shrink-0`}>
              <AtlasIcon name="back" />
            </Link>
            <h1 className="text-lg font-semibold tracking-tight text-gray-100 sm:text-xl">{t('stellar.title')}</h1>
          </div>
          <div className="flex min-w-0 items-end gap-2">
            <Link to="/help#stellar-viewer" className={`${actionClass} shrink-0`}>
              <AtlasIcon name="help" className="size-4" />{t('stellar.help')}
            </Link>
          </div>
        </div>
        {!!stellarSystem?.stars.length && (
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex min-w-0 flex-[1_0_100%] items-center gap-2 text-sm text-gray-300 sm:flex-none">
              <span className="shrink-0">{t('stellar.focusedBody')}</span>
              <select
                value={focusBodyId ?? ''}
                onChange={(event) => selectBody(event.target.value || null)}
                className="min-h-10 min-w-0 flex-1 rounded-md border border-space-border bg-space-panel px-2.5 text-sm text-gray-100 sm:w-48"
              >
                <option value="">{t('stellar.noFocus')}</option>
                <optgroup label={t('stellar.groupStars')}>
                  {stellarSystem.stars.map((star) => <option key={star.id} value={star.id}>{star.name ?? star.id}</option>)}
                </optgroup>
                {planets.length > 0 && (
                  <optgroup label={t('stellar.groupBodies')}>
                    {planets.map((planet) => <option key={planet.id} value={planet.id}>{planet.name ?? planet.id}</option>)}
                  </optgroup>
                )}
              </select>
            </label>
            {focusBodyId && (
              <>
                {hasOrbit && (
                  <button type="button" className={actionClass} onClick={() => requestFocus(focusBodyId, 'orbit')}>
                    <AtlasIcon name="orbit" className="size-4" />{t('stellar.viewOrbit')}
                  </button>
                )}
                {hasBodyRadius && (
                  <button type="button" className={actionClass} onClick={() => requestFocus(focusBodyId, 'close-up')}>
                    <AtlasIcon name="frame" className="size-4" />{t('stellar.closeUp')}
                  </button>
                )}
                <button ref={detailsButton} type="button" className={actionClass}
                  aria-expanded={detailsOpen} aria-controls={detailsOpen ? 'stellar-body-details' : undefined}
                  onClick={() => setDetailsBodyId(detailsOpen ? null : focusBodyId)}>
                  {t('stellar.details')}
                </button>
              </>
            )}
            {mapPath && (
              <div className="flex flex-wrap gap-2 sm:ml-auto">
                <Link className={`${actionClass} bg-space-panel`} to={`${worldPath}/map/${mapPath}${branchQuery}`}>
                  {t('stellar.openFlatMap')}<AtlasIcon name="arrow" className="size-4" />
                </Link>
                <Link className={`${actionClass} bg-space-panel`} to={`${worldPath}/globe/${mapPath}${branchQuery}`}>
                  {t('stellar.openGlobeMap')}<AtlasIcon name="arrow" className="size-4" />
                </Link>
              </div>
            )}
          </div>
        )}
      </header>

      {/* Viewer */}
      <div className="relative min-h-[min(24rem,65dvh)] flex-1">
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
            focusBodyId={focusBodyId}
            focusRequest={focusRequest}
            detailsOpen={detailsOpen}
            onCloseDetails={() => {
              setDetailsBodyId(null)
              detailsButton.current?.focus()
            }}
            selectedPlanetCvtMesh={selectedPlanetCvtMesh ?? null}
            bodyCatalog={bodyCatalog}
            starCatalog={starCatalog}
            onSelectionChange={handleSelectionChange}
          />
        )}
      </div>
    </div>
  )
}
