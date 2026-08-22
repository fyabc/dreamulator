import { useParams, Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { isStaticMode } from '../api/mode'
import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { formatRadius, formatMass } from '../viewers/utils/scale'
import NarratorPanel from '../components/NarratorPanel'
import BranchSelector from '../components/BranchSelector'
import LayerDocuments from '../components/LayerDocuments'
import CivMapPreview from '../components/civmap/CivMapPreview'
import MapPreviewCanvas from '../components/map/MapPreviewCanvas'
import LayerDag from '../components/LayerDag'
import StarfieldBackground from '../components/StarfieldBackground'
import { decodePngToFloat32 } from '../viewers/map/utils/imageCodec'

/** Pick a Unicode glyph + color class based on body type and mass. */
function bodyIcon(planetType: string | undefined, massEarth: number | undefined) {
  switch (planetType) {
    case 'natural_satellite':
      return { glyph: '☽', cls: 'text-gray-400' }
    case 'gas_giant':
      return { glyph: '●', cls: 'text-orange-400' }
    case 'ice_giant':
      return { glyph: '●', cls: 'text-cyan-400' }
    case 'ocean_world':
      return { glyph: '●', cls: 'text-blue-400' }
    case 'terrestrial':
      return { glyph: '●', cls: 'text-stone-400' }
    case 'dwarf':
      return { glyph: '·', cls: 'text-gray-500' }
    default:
      // Fallback: mass-based heuristic for bodies with generic "planet" type
      if (massEarth != null && massEarth >= 50) return { glyph: '●', cls: 'text-orange-400' }
      if (massEarth != null && massEarth >= 5) return { glyph: '●', cls: 'text-cyan-400' }
      return { glyph: '●', cls: 'text-stone-400' }
  }
}

/** Render free-form narrative text with section headers and bullet points. */
function renderNarrative(text: string) {
  const sections = text.trim().split(/\n\s*\n/).filter(Boolean)
  const intro = sections[0] ?? ''
  const rest = sections.slice(1)
  return (
    <>
      <p className="text-gray-300 text-sm leading-relaxed whitespace-pre-line mb-3">
        {intro}
      </p>
      {rest.map((section: string, i: number) => {
        const lines = section.split('\n').map((l: string) => l.trim())
        const header = lines[0]?.replace(/[：:]\s*$/, '') ?? ''
        const bullets = lines
          .slice(1)
          .filter((l: string) => l.startsWith('- ') || l.startsWith('— '))
          .map((l: string) => l.replace(/^[-—]\s*/, ''))
        const hasBullets = bullets.length > 0
        return (
          <div key={i} className="mt-3">
            <h4 className="text-sm font-semibold text-amber-300 mb-1.5">{header}</h4>
            {hasBullets ? (
              <ul className="space-y-1.5 text-sm text-gray-300">
                {bullets.map((b: string, j: number) => (
                  <li key={j} className="flex gap-2">
                    <span className="text-amber-500/60 mt-0.5 shrink-0">›</span>
                    <span className="leading-relaxed">{b}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-line">
                {lines.join('\n')}
              </p>
            )}
          </div>
        )
      })}
    </>
  )
}

export default function WorldDetail() {
  const { worldName } = useParams<{ worldName: string }>()
  const navigate = useNavigate()
  const { t } = useTranslation('worlds')
  const staticMode = isStaticMode()

  type TabType =
    | 'overview'
    | 'astronomy'
    | 'planets'
    | 'climate'
    | 'ecology'
    | 'civilization'
    | 'design-notes'
    | 'narrate'
  const availableTabs: TabType[] = staticMode
    ? ['overview', 'astronomy', 'planets', 'climate', 'ecology', 'civilization', 'design-notes']
    : [
        'overview',
        'astronomy',
        'planets',
        'climate',
        'ecology',
        'civilization',
        'design-notes',
        'narrate',
      ]

  const [searchParams, setSearchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState<TabType>(
    () => (searchParams.get('tab') as TabType) || 'overview',
  )

  // Branch and tab persisted in URL search params (?branch=ERE-if&tab=civilization)
  const selectedBranch = searchParams.get('branch') || null
  const setSelectedBranch = (branch: string | null) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (branch) next.set('branch', branch)
      else next.delete('branch')
      return next
    }, { replace: true })
  }

  // Sync activeTab to URL
  const setActiveTabAndPersist = (tab: TabType) => {
    setActiveTab(tab)
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (tab === 'overview') next.delete('tab')
      else next.set('tab', tab)
      // The selected document belongs to the previous tab's layer — drop it
      // so the new tab starts at its own _overview.md.
      next.delete('doc')
      return next
    }, { replace: true })
  }

  const {
    data: world,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['world', worldName],
    queryFn: () => api.getWorld(worldName!),
    enabled: !!worldName,
  })

  const { data: stellarSystem } = useQuery({
    queryKey: ['astronomy', worldName, selectedBranch],
    queryFn: () => api.getStellarSystem(worldName!, selectedBranch),
    enabled: !!worldName && activeTab === 'astronomy',
    retry: false,
  })

  const { data: systemCatalog } = useQuery({
    queryKey: ['systemCatalog', worldName, selectedBranch],
    queryFn: () => api.getSystemCatalog(worldName!, selectedBranch),
    enabled: !!worldName && activeTab === 'astronomy',
    retry: false,
  })

  const { data: planets } = useQuery({
    queryKey: ['planets', worldName, selectedBranch],
    queryFn: () => api.getPlanets(worldName!, selectedBranch),
    enabled: !!worldName && activeTab === 'planets',
    retry: false,
  })

  const { data: climateData } = useQuery({
    queryKey: ['climate', worldName, selectedBranch],
    queryFn: () => api.getClimate(worldName!, selectedBranch),
    enabled: !!worldName && activeTab === 'climate',
    retry: false,
  })

  const { data: ecologyData } = useQuery({
    queryKey: ['ecology', worldName, selectedBranch],
    queryFn: () => api.getEcology(worldName!, selectedBranch),
    enabled: !!worldName && activeTab === 'ecology',
    retry: false,
  })

  // Map preview data (always loaded for overview tab)
  const { data: mapPlanets } = useQuery({
    queryKey: ['mapPlanets', worldName, selectedBranch],
    queryFn: () => api.listMapPlanets(worldName!, selectedBranch),
    enabled: !!worldName,
    retry: false,
  })

  const firstMapPlanet = mapPlanets && mapPlanets.length > 0 ? mapPlanets[0] : null

  const { data: mapMeta } = useQuery({
    queryKey: ['mapMeta', worldName, firstMapPlanet, selectedBranch],
    queryFn: () => api.getMapMeta(worldName!, firstMapPlanet!, selectedBranch),
    enabled: !!worldName && !!firstMapPlanet,
    retry: false,
  })

  const { data: mapElevationBlob } = useQuery({
    queryKey: ['previewElevation', worldName, firstMapPlanet, selectedBranch],
    queryFn: () => api.getElevationBlob(worldName!, firstMapPlanet!, selectedBranch),
    enabled: !!worldName && !!firstMapPlanet,
    retry: false,
  })

  const [previewElevation, setPreviewElevation] = useState<Float32Array | null>(null)
  useEffect(() => {
    if (!mapElevationBlob) {
      setPreviewElevation(null)
      return
    }
    let cancelled = false
    decodePngToFloat32(mapElevationBlob).then(({ data }) => {
      if (!cancelled) setPreviewElevation(data)
    }).catch(() => {
      if (!cancelled) setPreviewElevation(null)
    })
    return () => { cancelled = true }
  }, [mapElevationBlob])

  const buildMutation = useMutation({
    mutationFn: () => api.buildWorld(worldName!),
  })

  const validateMutation = useMutation({
    mutationFn: () => api.validateWorld(worldName!),
  })

  const TAB_LABELS: Record<TabType, string> = {
    overview: t('tab.overview'),
    astronomy: t('tab.astronomy'),
    planets: t('tab.planets'),
    climate: t('tab.climate'),
    ecology: t('tab.ecology'),
    civilization: t('tab.civilization'),
    'design-notes': t('tab.designNotes'),
    narrate: t('tab.narrate'),
  }

  return (
    <div className="relative min-h-screen">
      <StarfieldBackground />

      <div className="relative z-10 px-3 sm:px-6 py-4 sm:py-8">
        {!worldName && (
          <div className="text-center py-12 text-gray-400">{t('status.noWorld')}</div>
        )}

        {isLoading && (
          <div className="text-center py-12 text-gray-400">{t('status.loading')}</div>
        )}

        {error && (
          <div className="text-center py-12 text-red-400">
            {t('status.loadError')}: {error.message}
          </div>
        )}

        {worldName && !isLoading && !error && (
          <>
            <div className="flex items-center gap-4 mb-4">
              <Link
                to="/worlds"
                className="text-gray-400 hover:text-neon-cyan transition-colors"
              >
                {t('action.back')}
              </Link>
              <h1 className="text-3xl font-bold text-neon-cyan neon-glow-subtle">
                {worldName}
              </h1>
              {staticMode && (
                <span className="text-xs px-2 py-0.5 rounded bg-space-surface text-gray-500 border border-space-border">
                  {t('detail.readonly')}
                </span>
              )}
            </div>

            <div className="mb-4">
              <BranchSelector
                worldName={worldName!}
                selectedBranch={selectedBranch}
                onSelect={setSelectedBranch}
              />
            </div>

            {/* Build/Validate buttons — only in API mode */}
            {!staticMode && (
              <div className="flex gap-3 mb-6">
                <button
                  onClick={() => validateMutation.mutate()}
                  disabled={validateMutation.isPending}
                  className="px-4 py-2 rounded-lg font-medium transition-all bg-space-surface text-gray-300 border border-space-border hover:border-neon-cyan/30 disabled:opacity-50"
                >
                  {validateMutation.isPending ? t('status.validating') : t('action.validateWorld')}
                </button>
                <button
                  onClick={() => buildMutation.mutate()}
                  disabled={buildMutation.isPending}
                  className="px-4 py-2 rounded-lg font-medium transition-all bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 disabled:opacity-50"
                >
                  {buildMutation.isPending ? t('status.building') : t('action.buildWorld')}
                </button>
              </div>
            )}

            {validateMutation.data && (
              <div
                className={`mb-6 p-4 rounded-lg border ${
                  validateMutation.data.ok
                    ? 'bg-green-900/30 border-green-500/20'
                    : 'bg-red-900/30 border-red-500/20'
                }`}
              >
                <p className="font-semibold mb-2">
                  {validateMutation.data.ok ? t('detail.valid') : t('detail.invalid')}
                </p>
                {validateMutation.data.errors.length > 0 && (
                  <ul className="list-disc list-inside text-sm">
                    {validateMutation.data.errors.map((err, i) => (
                      <li key={i} className="text-red-300">
                        {err}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {/* Tabs — horizontally scrollable on mobile */}
            <div className="flex gap-1 sm:gap-2 mb-4 sm:mb-6 border-b border-space-border overflow-x-auto">
              {availableTabs.map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTabAndPersist(tab)}
                  className={`px-3 sm:px-4 py-2 font-medium transition-colors border-b-2 whitespace-nowrap shrink-0 ${
                    activeTab === tab
                      ? 'border-neon-cyan text-neon-cyan neon-glow-subtle'
                      : 'border-transparent text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {TAB_LABELS[tab]}
                </button>
              ))}
            </div>

            {activeTab === 'overview' && world && (
              <div className="space-y-6">
                <section className="glass-panel p-4 sm:p-6">
                  <h2 className="text-xl font-semibold mb-4 text-neon-cyan neon-glow-subtle">
                    {t('detail.metadata')}
                  </h2>
                  {world.metadata?.description && (
                    <p className="text-gray-300 text-sm leading-relaxed mb-4">
                      {world.metadata.description}
                    </p>
                  )}
                  {world.metadata?.tags?.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-4">
                      {world.metadata.tags.map((tag: string) => (
                        <span
                          key={tag}
                          className="text-xs px-2 py-1 rounded bg-space-surface/60 text-gray-300 border border-space-border"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}
                  <dl className="grid grid-cols-2 gap-4">
                    <div>
                      <dt className="text-gray-500 text-sm">{t('detail.created')}</dt>
                      <dd className="font-medium mt-0.5">
                        {world.metadata?.created || 'N/A'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-gray-500 text-sm">{t('detail.version')}</dt>
                      <dd className="font-medium mt-0.5">
                        {world.metadata?.version || 'N/A'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-gray-500 text-sm">{t('detail.seed')}</dt>
                      <dd className="font-medium mt-0.5 font-mono">
                        {world.seed?.seed || 'N/A'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-gray-500 text-sm">{t('detail.dreamulatorVersion')}</dt>
                      <dd className="font-medium mt-0.5">
                        {world.metadata?.dreamulator_version || 'N/A'}
                      </dd>
                    </div>
                  </dl>
                </section>

                {world.stellar_system && (
                  <section className="glass-panel p-4 sm:p-6">
                    <h2 className="text-xl font-semibold mb-4 text-neon-cyan neon-glow-subtle">
                      {t('detail.starSystem')}
                    </h2>
                    <p className="mb-2">
                      <span className="text-gray-500">{t('field.name')}</span>
                      {world.stellar_system.name}
                    </p>
                    <p className="mb-2">
                      <span className="text-gray-500">{t('field.stars')}</span>
                      {world.stellar_system.stars?.length || 0}
                    </p>
                    <p>
                      <span className="text-gray-500">{t('field.orbit')}</span>
                      {world.stellar_system.orbits?.length || 0}
                    </p>
                  </section>
                )}

                {/* Map preview card */}
                <section className="glass-panel p-4 sm:p-6">
                  <h2 className="text-xl font-semibold mb-4 text-neon-cyan neon-glow-subtle">
                    {t('detail.map')}
                  </h2>
                  {firstMapPlanet ? (
                    <div>
                      <div
                        className="relative cursor-pointer group rounded-lg overflow-hidden"
                        onClick={() => {
                          const qs = selectedBranch ? `?branch=${encodeURIComponent(selectedBranch)}` : ''
                          navigate(`/worlds/${worldName}/globe/${encodeURIComponent(firstMapPlanet)}${qs}`)
                        }}
                      >
                        <MapPreviewCanvas
                          elevation={previewElevation}
                          width={mapMeta?.width ?? 2048}
                          height={mapMeta?.height ?? 1024}
                          seaLevel={mapMeta?.sea_level_m ?? 0.0}
                          className="w-full"
                        />
                        <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/50 rounded-lg">
                          <span className="text-neon-cyan font-medium">
                            {t('label.openMapEditor')}
                          </span>
                        </div>
                      </div>
                      <p className="text-sm text-gray-500 mt-2">
                        {firstMapPlanet} · {mapMeta?.width ?? '?'}×{mapMeta?.height ?? '?'}
                        {' · '}
                        {t('label.clickToView')}
                      </p>
                    </div>
                  ) : (
                    <div className="text-center py-6">
                      <p className="text-gray-500 mb-2">{t('status.noMapData')}</p>
                      <p className="text-xs text-gray-600 mb-3">
                        {t('status.mapGenerateHint')}
                      </p>
                      {!staticMode && (
                        <Link
                          to={`/worlds/${worldName}/map${selectedBranch ? `?branch=${encodeURIComponent(selectedBranch)}` : ''}`}
                          className="inline-block px-4 py-2 rounded-lg text-sm font-medium bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 transition-colors"
                        >
                          {t('action.generateFirstMap')}
                        </Link>
                      )}
                    </div>
                  )}
                </section>

                {/* Layer DAG visualisation */}
                {world.layers && (
                  <LayerDag
                    layers={world.layers}
                  />
                )}
              </div>
            )}

            {activeTab === 'astronomy' && (
              <div className="space-y-6">
              <div className="glass-panel p-4 sm:p-6">
                <h2 className="text-xl font-semibold mb-4 text-neon-cyan neon-glow-subtle">
                  {t('tab.astronomy')}
                </h2>
                {stellarSystem ? (
                  <div>
                    <p className="mb-4">
                      <span className="text-gray-500">{t('field.systemName')}</span>
                      {stellarSystem.name}
                    </p>

                    {/* System description / formation history */}
                    {stellarSystem.description && (
                      <section className="mb-6 bg-space-surface/40 rounded-lg p-5 border border-space-border">
                        {renderNarrative(stellarSystem.description as string)}
                      </section>
                    )}

                    {/* Body encyclopedia — merged system catalog (auto-generated
                        from stellar.yaml + planets.yaml; planets.yaml is
                        authoritative for shared fields) */}
                    {systemCatalog && (systemCatalog.bodies?.length > 0 || systemCatalog.stars?.length > 0) && (
                      <section className="mb-6">
                        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-3">
                          {t('detail.bodyEncyclopedia')}
                          <span className="ml-2 text-xs text-gray-600 normal-case tracking-normal">
                            {t('detail.bodyEncyclopediaHint')}
                          </span>
                        </h3>

                        {/* Star cards */}
                        {(systemCatalog.stars ?? []).length > 0 && (
                          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-3">
                            {(systemCatalog.stars as any[]).map((star: any) => (
                              <div
                                key={star.id}
                                className="bg-space-surface/60 rounded-lg p-4 border border-space-border"
                              >
                                <div className="flex items-center gap-2 mb-2">
                                  <span className="text-yellow-400">★</span>
                                  <span className="font-semibold text-neon-cyan">
                                    {star.name ?? star.id}
                                  </span>
                                  <span className="text-xs text-gray-600 font-mono">{star.id}</span>
                                  <span className="text-xs px-1.5 py-0.5 rounded bg-yellow-400/15 text-yellow-300 border border-yellow-400/20">
                                    {star.spectral_class ?? '?'}{star.luminosity_class ?? ''}
                                  </span>
                                </div>
                                <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-sm">
                                  {star.luminosity_sol != null && (
                                    <p><span className="text-gray-500">{t('field.luminosity')}</span>{star.luminosity_sol} L☉</p>
                                  )}
                                  {star.mass_sol != null && (
                                    <p><span className="text-gray-500">{t('field.mass')}</span>{star.mass_sol} M☉</p>
                                  )}
                                  {star.radius_sol != null && (
                                    <p><span className="text-gray-500">{t('field.radius')}</span>{star.radius_sol} R☉</p>
                                  )}
                                  {star.temperature_k != null && (
                                    <p><span className="text-gray-500">{t('field.temperature')}</span>{Math.round(star.temperature_k)} K</p>
                                  )}
                                  {star.age_gyr != null && (
                                    <p><span className="text-gray-500">{t('field.age')}</span>{star.age_gyr} Gyr</p>
                                  )}
                                  {star.ms_lifetime_gyr != null && (
                                    <p><span className="text-gray-500">{t('field.msLifetime')}</span>{star.ms_lifetime_gyr} Gyr</p>
                                  )}
                                  {star.evolution_progress != null && (
                                    <p>
                                      <span className="text-gray-500">{t('field.evolutionProgress')}</span>
                                      {(star.evolution_progress * 100).toFixed(1)}%
                                    </p>
                                  )}
                                  {star.habitable_zone_center_au != null && (
                                    <p><span className="text-gray-500">{t('field.habitableZoneCenter')}</span>{star.habitable_zone_center_au} AU</p>
                                  )}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Body cards — hierarchical by parent_id (satellites nest under
                            their planet; planets orbit the star shown above) */}
                        {(() => {
                          const bodies = (systemCatalog.bodies as any[]) ?? []
                          const bodyIds = new Set(bodies.map((b: any) => b.id))
                          const childrenOf = new Map<string, any[]>()
                          for (const b of bodies) {
                            if (b.parent_id && bodyIds.has(b.parent_id)) {
                              const list = childrenOf.get(b.parent_id) ?? []
                              list.push(b)
                              childrenOf.set(b.parent_id, list)
                            }
                          }
                          // Roots = bodies whose parent is a star (or unknown), i.e. not another body
                          const roots = bodies.filter(
                            (b: any) => !b.parent_id || !bodyIds.has(b.parent_id),
                          )

                          const renderBodyCard = (body: any) => {
                            const phys = body.physical ?? {}
                            const orb = body.orbit ?? {}
                            const der = body.derived ?? {}
                            const icon = bodyIcon(body.body_type, phys.mass_earth)
                            return (
                              <div className="bg-space-surface/60 rounded-lg p-4 border border-space-border">
                                <div className="flex items-center gap-2 mb-2 flex-wrap">
                                  <span className={icon.cls}>{icon.glyph}</span>
                                  <span className="font-semibold text-neon-cyan">
                                    {body.name ?? body.id}
                                  </span>
                                  <span className="text-xs text-gray-600 font-mono">{body.id}</span>
                                  {systemCatalog.target_body_id === body.id && (
                                    <span className="text-xs px-1.5 py-0.5 rounded bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/20">
                                      {t('detail.targetBody')}
                                    </span>
                                  )}
                                  {der.tidally_locked && (
                                    <span className="text-xs px-1.5 py-0.5 rounded bg-amber-400/15 text-amber-300 border border-amber-400/20">
                                      {t('detail.tidallyLocked')}
                                    </span>
                                  )}
                                  {der.in_conservative_habitable_zone && (
                                    <span className="text-xs px-1.5 py-0.5 rounded bg-green-400/15 text-green-300 border border-green-400/20">
                                      {t('detail.inHabitableZone')}
                                    </span>
                                  )}
                                </div>
                                <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                                  {phys.mass_earth != null && (
                                    <p><span className="text-gray-500">{t('field.mass')}</span>{formatMass(phys.mass_earth)}</p>
                                  )}
                                  {phys.radius_earth != null && (
                                    <p><span className="text-gray-500">{t('field.radius')}</span>{formatRadius(phys.radius_earth)}</p>
                                  )}
                                  {phys.gravity_m_s2 != null && (
                                    <p><span className="text-gray-500">{t('field.gravity')}</span>{phys.gravity_m_s2} m/s²</p>
                                  )}
                                  {phys.rotation_period_days != null && (
                                    <p><span className="text-gray-500">{t('field.rotation')}</span>{phys.rotation_period_days} {t('unit.days')}</p>
                                  )}
                                  {phys.axial_tilt_deg != null && (
                                    <p><span className="text-gray-500">{t('field.tilt')}</span>{phys.axial_tilt_deg}°</p>
                                  )}
                                  {phys.albedo != null && (
                                    <p><span className="text-gray-500">{t('field.albedo')}</span>{phys.albedo}</p>
                                  )}
                                  {orb.semi_major_axis_au != null && (
                                    <p>
                                      <span className="text-gray-500">{t('field.orbit')}</span>
                                      {orb.semi_major_axis_au < 0.01
                                        ? `${(orb.semi_major_axis_au * 149597870.7).toFixed(0)} km`
                                        : `${orb.semi_major_axis_au} AU`}
                                      {body.parent_id ? t('detail.orbiting', { parent: body.parent_id }) : ''}
                                    </p>
                                  )}
                                  {orb.period_days != null && (
                                    <p><span className="text-gray-500">{t('field.orbitalPeriod')}</span>{orb.period_days} {t('unit.days')}</p>
                                  )}
                                  {orb.eccentricity != null && (
                                    <p><span className="text-gray-500">{t('field.eccentricity')}</span>{orb.eccentricity}</p>
                                  )}
                                  {orb.inclination_deg != null && (
                                    <p><span className="text-gray-500">{t('field.inclination')}</span>{orb.inclination_deg}°</p>
                                  )}
                                  {der.instellation_earth_ratio != null && (
                                    <p><span className="text-gray-500">{t('field.instellation')}</span>{der.instellation_earth_ratio}{t('unit.earthRatio')}</p>
                                  )}
                                  {der.equilibrium_temperature_k != null && (
                                    <p><span className="text-gray-500">{t('field.equilibriumTemp')}</span>{der.equilibrium_temperature_k} K</p>
                                  )}
                                  {der.solar_day_days != null && (
                                    <p><span className="text-gray-500">{t('field.solarDay')}</span>{der.solar_day_days} {t('unit.days')}</p>
                                  )}
                                  {der.days_per_year != null && (
                                    <p><span className="text-gray-500">{t('field.daysPerYear')}</span>{der.days_per_year} {t('unit.solarDays')}</p>
                                  )}
                                  {body.atmosphere && (
                                    <p>
                                      <span className="text-gray-500">{t('field.atmosphere')}</span>
                                      {body.atmosphere.surface_pressure_atm ?? 1} atm
                                      {body.atmosphere.greenhouse_factor
                                        ? t('detail.greenhouse', { k: body.atmosphere.greenhouse_factor })
                                        : ''}
                                    </p>
                                  )}
                                  {body.hydrosphere?.water_coverage != null && (
                                    <p>
                                      <span className="text-gray-500">{t('field.waterCoverage')}</span>
                                      {Math.round(body.hydrosphere.water_coverage * 100)}%
                                    </p>
                                  )}
                                </div>
                                {body.description?.surface && (
                                  <p className="mt-2 pt-2 border-t border-space-border/50 text-sm text-gray-400">
                                    {body.description.surface}
                                  </p>
                                )}
                              </div>
                            )
                          }

                          const renderNode = (body: any, depth: number) => {
                            const children = childrenOf.get(body.id) ?? []
                            return (
                              <div key={body.id}>
                                <div style={{ marginLeft: depth * 24 }}>{renderBodyCard(body)}</div>
                                {children.length > 0 && (
                                  <div className="mt-3 space-y-3">
                                    {children.map((c: any) => renderNode(c, depth + 1))}
                                  </div>
                                )}
                              </div>
                            )
                          }

                          return (
                            <div className="space-y-3">
                              {roots.map((b: any) => renderNode(b, 0))}
                            </div>
                          )
                        })()}
                      </section>
                    )}

                  </div>
                ) : (
                  <p className="text-gray-500">{t('detail.noStarSystem')}</p>
                )}
              </div>
              <LayerDocuments worldName={worldName!} layer="astronomy" branch={selectedBranch} />
              </div>
            )}

            {activeTab === 'planets' && (
              <div className="space-y-6">
              <div className="glass-panel p-4 sm:p-6">
                <h2 className="text-xl font-semibold mb-4 text-neon-cyan neon-glow-subtle">
                  {t('tab.planets')}
                </h2>
                {planets ? (
                  <div className="space-y-4">
                    {planets.length > 0 ? (
                      planets.map((planet: any) => (
                        <div
                          key={planet.id}
                          className="bg-space-surface/60 rounded-lg p-4 border border-space-border"
                        >
                          <div className="flex items-center gap-2 mb-3">
                            <span className={bodyIcon(planet.planet_type, planet.mass).cls}>
                              {bodyIcon(planet.planet_type, planet.mass).glyph}
                            </span>
                            <span className="font-semibold text-neon-cyan">
                              {planet.name}
                            </span>
                            <span className="text-xs text-gray-600 font-mono">
                              {planet.id}
                            </span>
                            <span className="text-xs px-1.5 py-0.5 rounded bg-space-surface text-gray-400 border border-space-border">
                              {planet.planet_type}
                            </span>
                          </div>

                          {/* Physical properties */}
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 text-sm mb-3">
                            <p>
                              <span className="text-gray-500">{t('field.orbit')}</span>
                              {planet.orbits}
                            </p>
                            <p>
                              <span className="text-gray-500">{t('field.mass')}</span>
                              {formatMass(planet.mass)}
                            </p>
                            <p>
                              <span className="text-gray-500">{t('field.radius')}</span>
                              {formatRadius(planet.radius)}
                            </p>
                            <p>
                              <span className="text-gray-500">{t('field.albedo')}</span>
                              {planet.albedo ?? '—'}
                            </p>
                            {planet.rotation_period_days != null && (
                              <p>
                                <span className="text-gray-500">{t('field.rotationPeriod')}</span>
                                {planet.rotation_period_days} {t('unit.days')}
                              </p>
                            )}
                            {planet.axial_tilt_deg != null && (
                              <p>
                                <span className="text-gray-500">{t('field.axialTilt')}</span>
                                {planet.axial_tilt_deg}°
                              </p>
                            )}
                            {planet.magnetic_field_strength != null && (
                              <p>
                                <span className="text-gray-500">{t('field.magneticField')}</span>
                                {planet.magnetic_field_strength} μT
                              </p>
                            )}
                          </div>

                          {/* Sub-systems: atmosphere, hydrosphere, lithosphere */}
                          <div className="flex flex-wrap gap-2 text-xs">
                            {planet.atmosphere && (
                              <span className="px-2 py-1 rounded bg-blue-900/30 text-blue-300 border border-blue-800/30">
                                {t('badge.atmosphere')} {planet.atmosphere.surface_pressure_atm} atm
                                {planet.atmosphere.composition &&
                                  ` · ${Object.keys(planet.atmosphere.composition).join(', ')}`}
                              </span>
                            )}
                            {planet.hydrosphere && (
                              <span className="px-2 py-1 rounded bg-cyan-900/30 text-cyan-300 border border-cyan-800/30">
                                {t('badge.hydrosphere')} {Math.round((planet.hydrosphere.water_coverage ?? 0) * 100)}%
                                {planet.hydrosphere.salinity_ppt != null &&
                                  ` · ${planet.hydrosphere.salinity_ppt}‰`}
                              </span>
                            )}
                            {planet.lithosphere && (
                              <span className="px-2 py-1 rounded bg-amber-900/30 text-amber-300 border border-amber-800/30">
                                {t('badge.lithosphere')}
                                {planet.lithosphere.has_plate_tectonics
                                  ? ` · ${planet.lithosphere.num_plates} ${t('badge.plates')}`
                                  : ` · ${t('badge.noPlates')}`}
                              </span>
                            )}
                            {planet.satellite_ids?.length > 0 && (
                              <span className="px-2 py-1 rounded bg-purple-900/30 text-purple-300 border border-purple-800/30">
                                {planet.satellite_ids.length} {t('badge.satellites')}
                              </span>
                            )}
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="text-gray-500">{t('detail.noGeologyData')}</p>
                    )}
                  </div>
                ) : (
                  <p className="text-gray-500">{t('detail.noGeologyLayer')}</p>
                )}
              </div>
              <LayerDocuments worldName={worldName!} layer="geological" branch={selectedBranch} />
              </div>
            )}

            {activeTab === 'climate' && (
              <div className="space-y-6">
              <div className="glass-panel p-4 sm:p-6">
                <h2 className="text-xl font-semibold mb-4 text-neon-cyan neon-glow-subtle">
                  {t('tab.climate')}
                </h2>
                {climateData ? (
                  <pre className="text-sm text-gray-300 whitespace-pre-wrap font-mono bg-space-surface/40 rounded-lg p-4 overflow-auto">
                    {JSON.stringify(climateData, null, 2)}
                  </pre>
                ) : (
                  <p className="text-gray-500">{t('detail.noClimateData')}</p>
                )}
              </div>
              <LayerDocuments worldName={worldName!} layer="climate" branch={selectedBranch} />
              </div>
            )}

            {activeTab === 'ecology' && (
              <div className="space-y-6">
              <div className="glass-panel p-4 sm:p-6">
                <h2 className="text-xl font-semibold mb-4 text-neon-cyan neon-glow-subtle">
                  {t('tab.ecology')}
                </h2>
                {ecologyData ? (
                  <pre className="text-sm text-gray-300 whitespace-pre-wrap font-mono bg-space-surface/40 rounded-lg p-4 overflow-auto">
                    {JSON.stringify(ecologyData, null, 2)}
                  </pre>
                ) : (
                  <p className="text-gray-500">{t('detail.noEcologyData')}</p>
                )}
              </div>
              <LayerDocuments worldName={worldName!} layer="ecology" branch={selectedBranch} />
              </div>
            )}

            {activeTab === 'civilization' && (
              <div className="space-y-6">
                {/* Civilization Map preview */}
                <CivMapPreview worldName={worldName!} branch={selectedBranch} />

                {/* Markdown document viewer — shows docs or nothing */}
                <LayerDocuments worldName={worldName!} layer="civilization" branch={selectedBranch} />
              </div>
            )}

            {activeTab === 'design-notes' && (
              <LayerDocuments worldName={worldName!} layer="design-notes" branch={selectedBranch} />
            )}

            {activeTab === 'narrate' && !staticMode && (
              <NarratorPanel worldName={worldName!} branch={selectedBranch} />
            )}
          </>
        )}
      </div>
    </div>
  )
}
