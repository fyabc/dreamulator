import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { isStaticMode } from '../api/mode'
import { useState } from 'react'
import NarratorPanel from '../components/NarratorPanel'
import BranchSelector from '../components/BranchSelector'

export default function WorldDetail() {
  const { worldName } = useParams<{ worldName: string }>()
  const staticMode = isStaticMode()

  type TabType = 'overview' | 'astronomy' | 'planets' | 'narrate'
  const availableTabs: TabType[] = staticMode
    ? ['overview', 'astronomy', 'planets']
    : ['overview', 'astronomy', 'planets', 'narrate']

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
    queryKey: ['astronomy', worldName],
    queryFn: () => api.getStellarSystem(worldName!),
    enabled: !!worldName && activeTab === 'astronomy',
    retry: false,
  })

  const { data: planets } = useQuery({
    queryKey: ['planets', worldName],
    queryFn: () => api.getPlanets(worldName!),
    enabled: !!worldName && activeTab === 'planets',
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
    planets: '行星',
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
                    <h3 className="text-lg font-semibold mb-3">恒星</h3>
                    <div className="space-y-3">
                      {stellarSystem.stars?.map((star: any) => (
                        <div
                          key={star.id}
                          className="bg-space-surface/60 rounded-lg p-4 border border-space-border"
                        >
                          <p className="font-semibold text-neon-cyan mb-2">
                            {star.name} ({star.id})
                          </p>
                          <div className="grid grid-cols-2 gap-2 text-sm">
                            <p>
                              <span className="text-gray-500">类型：</span>
                              {star.spectral_class}
                              {star.luminosity_class}
                            </p>
                            <p>
                              <span className="text-gray-500">质量：</span>
                              {star.derived?.computed_mass ?? star.mass ?? 'N/A'} M☉
                            </p>
                            {(star.derived?.computed_temperature ?? star.temperature) && (
                              <p>
                                <span className="text-gray-500">温度：</span>
                                {star.derived?.computed_temperature ?? star.temperature} K
                              </p>
                            )}
                            {(star.derived?.computed_luminosity ?? star.luminosity) && (
                              <p>
                                <span className="text-gray-500">光度：</span>
                                {star.derived?.computed_luminosity ?? star.luminosity} L☉
                              </p>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <p className="text-gray-500">无恒星系数据</p>
                )}
              </div>
            )}

            {activeTab === 'planets' && (
              <div className="glass-panel p-6">
                <h2 className="text-xl font-semibold mb-4 text-neon-cyan neon-glow-subtle">
                  行星
                </h2>
                {planets ? (
                  <div className="space-y-3">
                    {planets.length > 0 ? (
                      planets.map((planet: any) => (
                        <div
                          key={planet.id}
                          className="bg-space-surface/60 rounded-lg p-4 border border-space-border"
                        >
                          <p className="font-semibold text-neon-cyan mb-2">
                            {planet.name} ({planet.id})
                          </p>
                          <div className="grid grid-cols-2 gap-2 text-sm">
                            <p>
                              <span className="text-gray-500">类型：</span>
                              {planet.planet_type}
                            </p>
                            <p>
                              <span className="text-gray-500">轨道：</span>
                              {planet.orbits}
                            </p>
                            <p>
                              <span className="text-gray-500">质量：</span>
                              {planet.mass} M⊕
                            </p>
                            <p>
                              <span className="text-gray-500">半径：</span>
                              {planet.radius} R⊕
                            </p>
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="text-gray-500">未定义行星</p>
                    )}
                  </div>
                ) : (
                  <p className="text-gray-500">无行星数据</p>
                )}
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
