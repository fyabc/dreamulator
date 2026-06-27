import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { isStaticMode } from '../api/mode'
import { useState } from 'react'
import { formatRadius, formatMass } from '../viewers/utils/scale'
import NarratorPanel from '../components/NarratorPanel'
import BranchSelector from '../components/BranchSelector'
import StellarSystemViewer from '../viewers/StellarSystemViewer'

export default function WorldDetail() {
  const { worldName } = useParams<{ worldName: string }>()
  const staticMode = isStaticMode()

  type TabType = 'overview' | 'astronomy' | 'planets' | 'viewer3d' | 'narrate'
  const availableTabs: TabType[] = staticMode
    ? ['overview', 'astronomy', 'planets', 'viewer3d']
    : ['overview', 'astronomy', 'planets', 'viewer3d', 'narrate']

  const [activeTab, setActiveTab] = useState<TabType>('overview')
  const [selectedBranch, setSelectedBranch] = useState<string | null>(null)

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
    enabled: !!worldName && (activeTab === 'astronomy' || activeTab === 'viewer3d'),
    retry: false,
  })

  const { data: planets } = useQuery({
    queryKey: ['planets', worldName, selectedBranch],
    queryFn: () => api.getPlanets(worldName!, selectedBranch),
    enabled: !!worldName && (activeTab === 'planets' || activeTab === 'viewer3d'),
    retry: false,
  })

  const { data: habitableZones } = useQuery({
    queryKey: ['habitable-zones', worldName, selectedBranch],
    queryFn: () => api.getHabitableZones(worldName!, selectedBranch),
    enabled: !!worldName && activeTab === 'viewer3d',
    retry: false,
  })

  const buildMutation = useMutation({
    mutationFn: () => api.buildWorld(worldName!),
  })

  const validateMutation = useMutation({
    mutationFn: () => api.validateWorld(worldName!),
  })

  const TAB_LABELS: Record<TabType, string> = {
    overview: '概览',
    astronomy: '天文学',
    planets: '地质',
    viewer3d: '3D 视图',
    narrate: '叙述',
  }

  return (
    <div className="relative min-h-screen">
      <div className="starfield" />
      <div className="nebula" />

      <div className="relative z-10 px-6 py-8">
        {!worldName && (
          <div className="text-center py-12 text-gray-400">未选择世界</div>
        )}

        {isLoading && (
          <div className="text-center py-12 text-gray-400">加载中...</div>
        )}

        {error && (
          <div className="text-center py-12 text-red-400">
            加载失败: {error.message}
          </div>
        )}

        {worldName && !isLoading && !error && (
          <>
            <div className="flex items-center gap-4 mb-4">
              <Link
                to="/worlds"
                className="text-gray-400 hover:text-neon-cyan transition-colors"
              >
                ← 返回
              </Link>
              <h1 className="text-3xl font-bold text-neon-cyan neon-glow-subtle">
                {worldName}
              </h1>
              {staticMode && (
                <span className="text-xs px-2 py-0.5 rounded bg-space-surface text-gray-500 border border-space-border">
                  只读模式
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
                  {validateMutation.isPending ? '验证中...' : '验证'}
                </button>
                <button
                  onClick={() => buildMutation.mutate()}
                  disabled={buildMutation.isPending}
                  className="px-4 py-2 rounded-lg font-medium transition-all bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 disabled:opacity-50"
                >
                  {buildMutation.isPending ? '构建中...' : '构建'}
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
                  {validateMutation.data.ok ? '✓ 有效' : '✗ 无效'}
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

            {/* Tabs */}
            <div className="flex gap-2 mb-6 border-b border-space-border">
              {availableTabs.map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-4 py-2 font-medium transition-colors border-b-2 ${
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
                <section className="glass-panel p-6">
                  <h2 className="text-xl font-semibold mb-4 text-neon-cyan neon-glow-subtle">
                    元数据
                  </h2>
                  <dl className="grid grid-cols-2 gap-4">
                    <div>
                      <dt className="text-gray-500 text-sm">创建时间</dt>
                      <dd className="font-medium mt-0.5">
                        {world.metadata?.created || 'N/A'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-gray-500 text-sm">版本</dt>
                      <dd className="font-medium mt-0.5">
                        {world.metadata?.version || 'N/A'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-gray-500 text-sm">种子</dt>
                      <dd className="font-medium mt-0.5 font-mono">
                        {world.seed?.seed || 'N/A'}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-gray-500 text-sm">Dreamulator 版本</dt>
                      <dd className="font-medium mt-0.5">
                        {world.metadata?.dreamulator_version || 'N/A'}
                      </dd>
                    </div>
                  </dl>
                </section>

                {world.stellar_system && (
                  <section className="glass-panel p-6">
                    <h2 className="text-xl font-semibold mb-4 text-neon-cyan neon-glow-subtle">
                      恒星系
                    </h2>
                    <p className="mb-2">
                      <span className="text-gray-500">名称：</span>
                      {world.stellar_system.name}
                    </p>
                    <p className="mb-2">
                      <span className="text-gray-500">恒星：</span>
                      {world.stellar_system.stars?.length || 0}
                    </p>
                    <p>
                      <span className="text-gray-500">轨道：</span>
                      {world.stellar_system.orbits?.length || 0}
                    </p>
                  </section>
                )}
              </div>
            )}

            {activeTab === 'astronomy' && (
              <div className="glass-panel p-6">
                <h2 className="text-xl font-semibold mb-4 text-neon-cyan neon-glow-subtle">
                  天文学
                </h2>
                {stellarSystem ? (
                  <div>
                    <p className="mb-4">
                      <span className="text-gray-500">系统名称：</span>
                      {stellarSystem.name}
                    </p>

                    {/* Orbit hierarchy — tree view */}
                    {(() => {
                      const orbits: any[] = stellarSystem.orbits ?? []
                      const bodies: any[] = stellarSystem.bodies ?? []
                      const stars: any[] = stellarSystem.stars ?? []
                      const bodyById = new Map(bodies.map((b: any) => [b.id, b]))
                      const childrenOf = new Map<string, any[]>()
                      for (const o of orbits) {
                        const list = childrenOf.get(o.parent_id) ?? []
                        list.push(o)
                        childrenOf.set(o.parent_id, list)
                      }

                      const renderBody = (bodyId: string, depth: number) => {
                        const orbit = orbits.find((o: any) => o.body_id === bodyId)
                        const body = bodyById.get(bodyId)
                        const children = childrenOf.get(bodyId) ?? []
                        const indent = depth * 24

                        return (
                          <div key={bodyId}>
                            <div
                              className="bg-space-surface/60 rounded-lg p-3 border border-space-border"
                              style={{ marginLeft: indent }}
                            >
                              <div className="flex items-center gap-2 mb-1">
                                <span className="font-semibold text-neon-cyan">
                                  {body?.name ?? bodyId}
                                </span>
                                <span className="text-xs text-gray-600 font-mono">
                                  {bodyId}
                                </span>
                              </div>
                              <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1 text-sm">
                                {orbit && (
                                  <>
                                    <p>
                                      <span className="text-gray-500">半长轴：</span>
                                      {orbit.semi_major_axis_au < 0.01
                                        ? `${(orbit.semi_major_axis_au * 149597870.7).toFixed(0)} km`
                                        : `${orbit.semi_major_axis_au} AU`}
                                    </p>
                                    <p>
                                      <span className="text-gray-500">离心率：</span>
                                      {orbit.eccentricity}
                                    </p>
                                    <p>
                                      <span className="text-gray-500">倾角：</span>
                                      {orbit.inclination_deg}°
                                    </p>
                                  </>
                                )}
                                {body && (
                                  <>
                                    <p>
                                      <span className="text-gray-500">类型：</span>
                                      {body.planet_type ?? body.body_type ?? '—'}
                                    </p>
                                    <p>
                                      <span className="text-gray-500">质量：</span>
                                      {body.mass != null ? formatMass(body.mass) : '—'}
                                    </p>
                                    <p>
                                      <span className="text-gray-500">半径：</span>
                                      {body.radius != null ? formatRadius(body.radius) : '—'}
                                    </p>
                                  </>
                                )}
                              </div>
                            </div>
                            {/* Recursive children */}
                            {children.map((child: any) =>
                              renderBody(child.body_id, depth + 1),
                            )}
                          </div>
                        )
                      }

                      return (
                        <div className="space-y-2">
                          {stars.map((star: any) => {
                            const starChildren = childrenOf.get(star.id) ?? []
                            return (
                              <div key={star.id}>
                                {/* Star */}
                                <div className="bg-space-surface/60 rounded-lg p-4 border border-space-border">
                                  <div className="flex items-center gap-2 mb-2">
                                    <span className="text-yellow-400">★</span>
                                    <span className="font-semibold text-neon-cyan">
                                      {star.name}
                                    </span>
                                    <span className="text-xs text-gray-600 font-mono">
                                      {star.id}
                                    </span>
                                  </div>
                                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 text-sm">
                                    <p>
                                      <span className="text-gray-500">光谱型：</span>
                                      {star.spectral_class}
                                      {star.luminosity_class}
                                    </p>
                                    <p>
                                      <span className="text-gray-500">质量：</span>
                                      {star.derived?.computed_mass ?? star.mass ?? 'N/A'} M☉
                                    </p>
                                    <p>
                                      <span className="text-gray-500">温度：</span>
                                      {star.derived?.computed_temperature ?? star.temperature ?? 'N/A'} K
                                    </p>
                                    <p>
                                      <span className="text-gray-500">光度：</span>
                                      {star.derived?.computed_luminosity ?? star.luminosity ?? 'N/A'} L☉
                                    </p>
                                  </div>
                                </div>
                                {/* Orbiting bodies (tree) */}
                                <div className="mt-2 space-y-2">
                                  {starChildren.map((child: any) =>
                                    renderBody(child.body_id, 1),
                                  )}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      )
                    })()}
                  </div>
                ) : (
                  <p className="text-gray-500">无恒星系数据</p>
                )}
              </div>
            )}

            {activeTab === 'planets' && (
              <div className="glass-panel p-6">
                <h2 className="text-xl font-semibold mb-4 text-neon-cyan neon-glow-subtle">
                  地质
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
                              <span className="text-gray-500">轨道：</span>
                              {planet.orbits}
                            </p>
                            <p>
                              <span className="text-gray-500">质量：</span>
                              {formatMass(planet.mass)}
                            </p>
                            <p>
                              <span className="text-gray-500">半径：</span>
                              {formatRadius(planet.radius)}
                            </p>
                            <p>
                              <span className="text-gray-500">反照率：</span>
                              {planet.albedo ?? '—'}
                            </p>
                            {planet.rotation_period_days != null && (
                              <p>
                                <span className="text-gray-500">自转周期：</span>
                                {planet.rotation_period_days} 天
                              </p>
                            )}
                            {planet.axial_tilt_deg != null && (
                              <p>
                                <span className="text-gray-500">轴倾角：</span>
                                {planet.axial_tilt_deg}°
                              </p>
                            )}
                            {planet.magnetic_field_strength != null && (
                              <p>
                                <span className="text-gray-500">磁场：</span>
                                {planet.magnetic_field_strength} μT
                              </p>
                            )}
                          </div>

                          {/* Sub-systems: atmosphere, hydrosphere, lithosphere */}
                          <div className="flex flex-wrap gap-2 text-xs">
                            {planet.atmosphere && (
                              <span className="px-2 py-1 rounded bg-blue-900/30 text-blue-300 border border-blue-800/30">
                                大气 {planet.atmosphere.surface_pressure_atm} atm
                                {planet.atmosphere.composition &&
                                  ` · ${Object.keys(planet.atmosphere.composition).join(', ')}`}
                              </span>
                            )}
                            {planet.hydrosphere && (
                              <span className="px-2 py-1 rounded bg-cyan-900/30 text-cyan-300 border border-cyan-800/30">
                                水圈 {Math.round((planet.hydrosphere.water_coverage ?? 0) * 100)}%
                                {planet.hydrosphere.salinity_ppt != null &&
                                  ` · ${planet.hydrosphere.salinity_ppt}‰`}
                              </span>
                            )}
                            {planet.lithosphere && (
                              <span className="px-2 py-1 rounded bg-amber-900/30 text-amber-300 border border-amber-800/30">
                                岩石圈
                                {planet.lithosphere.has_plate_tectonics
                                  ? ` · ${planet.lithosphere.num_plates} 板块`
                                  : ' · 无板块'}
                              </span>
                            )}
                            {planet.satellite_ids?.length > 0 && (
                              <span className="px-2 py-1 rounded bg-purple-900/30 text-purple-300 border border-purple-800/30">
                                {planet.satellite_ids.length} 卫星
                              </span>
                            )}
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="text-gray-500">未定义地质数据</p>
                    )}
                  </div>
                ) : (
                  <p className="text-gray-500">无地质层数据</p>
                )}
              </div>
            )}

            {activeTab === 'viewer3d' && (
              <div>
                <h2 className="text-xl font-semibold mb-4 text-neon-cyan neon-glow-subtle">
                  恒星系 3D 可视化
                </h2>
                <StellarSystemViewer
                  stellar={stellarSystem}
                  planets={planets}
                  habitableZones={habitableZones}
                />
              </div>
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
