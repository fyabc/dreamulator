import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'

/** Canonical layer order from the engine DAG. */
const LAYER_ORDER = [
  'physics',
  'chemistry',
  'stellar',
  'orbital',
  'geological',
  'climate',
  'ecology',
  'civilization',
]

/** Chinese labels for layers. */
const LAYER_LABELS: Record<string, string> = {
  physics: '物理定律',
  chemistry: '化学',
  stellar: '恒星系',
  orbital: '轨道力学',
  geological: '地质',
  climate: '气候',
  ecology: '生态',
  civilization: '文明',
}

export default function WorldInfo() {
  const [selectedWorld, setSelectedWorld] = useState<string | null>(null)

  const {
    data: worlds,
    isLoading: loadingWorlds,
    error: listError,
  } = useQuery({
    queryKey: ['worlds'],
    queryFn: api.listWorlds,
  })

  const {
    data: worldData,
    isLoading: loadingDetail,
    error: detailError,
  } = useQuery({
    queryKey: ['world', selectedWorld],
    queryFn: () => api.getWorld(selectedWorld!),
    enabled: !!selectedWorld,
  })

  return (
    <div className="relative min-h-screen">
      {/* Background */}
      <div className="starfield" />
      <div className="nebula" />

      {/* Content */}
      <div className="relative z-10 max-w-4xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center gap-4 mb-8">
          <h1 className="text-3xl font-bold text-neon-cyan neon-glow-subtle">
            世界信息
          </h1>
        </div>

        {/* World selector */}
        <div className="glass-panel p-4 mb-6">
          <label className="block text-sm text-gray-400 mb-2">选择世界</label>
          {loadingWorlds ? (
            <p className="text-gray-500">加载中...</p>
          ) : listError ? (
            <p className="text-red-400 text-sm">无法连接后端服务</p>
          ) : worlds && worlds.length > 0 ? (
            <select
              value={selectedWorld ?? ''}
              onChange={(e) => setSelectedWorld(e.target.value || null)}
              className="w-full bg-space-bg border border-space-border rounded-lg px-4 py-2.5 text-white focus:outline-none focus:border-neon-cyan transition-colors"
            >
              <option value="">— 请选择 —</option>
              {worlds.map((w) => (
                <option key={w} value={w}>
                  {w}
                </option>
              ))}
            </select>
          ) : (
            <p className="text-gray-500">暂无世界，请先创建一个世界</p>
          )}
        </div>

        {/* Loading / error states */}
        {loadingDetail && (
          <div className="glass-panel p-8 text-center text-gray-400">
            加载世界数据...
          </div>
        )}

        {detailError && (
          <div className="glass-panel p-6 border-red-500/30">
            <p className="text-red-400">加载失败: {detailError.message}</p>
          </div>
        )}

        {/* World detail */}
        {worldData && !loadingDetail && <WorldDetail data={worldData} />}

        {/* Empty state */}
        {!selectedWorld && !loadingDetail && (
          <div className="glass-panel p-12 text-center">
            <p className="text-gray-500 text-lg">选择一个世界以查看其配置信息</p>
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * Renders the full configuration detail for a selected world.
 */
function WorldDetail({ data }: { data: any }) {
  const meta = data.metadata ?? {}
  const seed = data.seed ?? {}
  const layers = data.layers ?? {}
  const planetIds: string[] = data.planet_ids ?? []
  const tags: string[] = meta.tags ?? []

  return (
    <div className="space-y-6">
      {/* Metadata */}
      <section className="glass-panel p-6">
        <h2 className="text-xl font-semibold text-neon-cyan neon-glow-subtle mb-4">
          基本信息
        </h2>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-4">
          <InfoRow label="名称" value={meta.name} />
          <InfoRow label="版本" value={meta.version} />
          <InfoRow label="描述" value={meta.description} wide />
          <InfoRow label="创建时间" value={formatDate(meta.created)} />
          <InfoRow label="修改时间" value={formatDate(meta.modified)} />
          <InfoRow label="Dreamulator 版本" value={meta.dreamulator_version} />
        </dl>
        {tags.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {tags.map((tag: string) => (
              <span
                key={tag}
                className="px-2.5 py-0.5 rounded-full text-xs bg-neon-purple/20 text-neon-purple border border-neon-purple/30"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </section>

      {/* Seed */}
      <section className="glass-panel p-6">
        <h2 className="text-xl font-semibold text-neon-cyan neon-glow-subtle mb-4">
          随机种子
        </h2>
        <p className="font-mono text-lg text-gray-200">{seed.seed ?? 'N/A'}</p>
      </section>

      {/* Layer DAG */}
      <section className="glass-panel p-6">
        <h2 className="text-xl font-semibold text-neon-cyan neon-glow-subtle mb-4">
          层级架构
        </h2>
        <p className="text-sm text-gray-500 mb-6">
          引擎按以下顺序推演：从基础物理到文明演化
        </p>

        <div className="space-y-1">
          {LAYER_ORDER.map((layer, i) => {
            const info = layers[layer]
            const configured = info?.configured ?? false
            const engine = info?.engine || ''
            const isLast = i === LAYER_ORDER.length - 1

            return (
              <div key={layer}>
                {/* Layer card */}
                <div
                  className={`flex items-center gap-4 p-3 rounded-lg transition-colors ${
                    configured
                      ? 'bg-space-surface/60 border border-neon-cyan/10'
                      : 'bg-space-bg/40 border border-transparent'
                  }`}
                >
                  {/* Status indicator */}
                  <div className="flex-shrink-0">
                    <div
                      className={`w-3 h-3 rounded-full ${
                        configured
                          ? 'bg-neon-cyan shadow-[0_0_6px_rgba(0,212,255,0.6)]'
                          : 'bg-gray-600'
                      }`}
                    />
                  </div>

                  {/* Layer name */}
                  <div className="flex-1 min-w-0">
                    <span
                      className={`font-medium ${
                        configured ? 'text-white' : 'text-gray-500'
                      }`}
                    >
                      {LAYER_LABELS[layer] ?? layer}
                    </span>
                    <span className="text-gray-600 text-sm ml-2">{layer}</span>
                  </div>

                  {/* Engine badge */}
                  {configured && engine && (
                    <span className="text-xs px-2 py-0.5 rounded bg-neon-cyan/10 text-neon-cyan border border-neon-cyan/20">
                      {engine}
                    </span>
                  )}

                  {/* Status label */}
                  <span
                    className={`text-xs ${
                      configured ? 'text-neon-cyan/70' : 'text-gray-600'
                    }`}
                  >
                    {configured ? '已配置' : '未配置'}
                  </span>
                </div>

                {/* Connector arrow */}
                {!isLast && (
                  <div className="flex justify-start pl-[5px] py-0.5">
                    <div className="w-px h-3 bg-space-border" />
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </section>

      {/* Planets */}
      <section className="glass-panel p-6">
        <h2 className="text-xl font-semibold text-neon-cyan neon-glow-subtle mb-4">
          行星列表
        </h2>
        {planetIds.length > 0 ? (
          <div className="flex flex-wrap gap-3">
            {planetIds.map((id: string) => (
              <div
                key={id}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-space-surface/60 border border-space-border"
              >
                <span className="text-neon-cyan text-sm">●</span>
                <span className="font-mono text-sm text-gray-200">{id}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-gray-500">未定义行星</p>
        )}
      </section>

      {/* Branch info */}
      {data.branch && (
        <section className="glass-panel p-6">
          <h2 className="text-xl font-semibold text-neon-cyan neon-glow-subtle mb-4">
            分支信息
          </h2>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-4">
            <InfoRow label="分支名称" value={data.branch.name} />
            <InfoRow label="分叉层级" value={data.branch.fork_layer} />
            <InfoRow label="父世界" value={data.branch.parent ?? '(根世界)'} />
          </dl>
        </section>
      )}
    </div>
  )
}

function InfoRow({
  label,
  value,
  wide,
}: {
  label: string
  value: string | undefined
  wide?: boolean
}) {
  return (
    <div className={wide ? 'sm:col-span-2' : ''}>
      <dt className="text-gray-500 text-sm">{label}</dt>
      <dd className="text-gray-200 font-medium mt-0.5">{value || 'N/A'}</dd>
    </div>
  )
}

function formatDate(iso: string | undefined): string {
  if (!iso) return 'N/A'
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}
