/**
 * HelpPage — global reference page accessible from sidebar "?".
 *
 * Covers: project concepts, map controls, CLI quick-start, layers,
 * and links to full documentation.
 *
 * TODO: searchable, Markdown-rendered help system.
 */

export default function HelpPage() {
  return (
    <div className="max-w-3xl mx-auto p-6 space-y-8">
      <div className="mb-2 p-3 rounded bg-yellow-900/20 border border-yellow-700/30 text-sm text-yellow-300">
        🚧 完整帮助系统待实现。以下为快速参考。
      </div>

      {/* --- CLI Quick Start --- */}
      <section>
        <h2 className="text-lg font-bold text-neon-cyan mb-3">CLI 快速入门</h2>
        <div className="bg-space-surface rounded-lg p-4 font-mono text-sm space-y-2 text-gray-300">
          <div><span className="text-gray-500"># 创建世界</span></div>
          <div>dreamulator init myworld --template earthlike</div>
          <div className="mt-2"><span className="text-gray-500"># 生成地形（快速迭代）</span></div>
          <div>dreamulator terrain generate earth -p earth -b terrain-dev -n 4096 --seed 42</div>
          <div className="mt-2"><span className="text-gray-500"># 时间演化（125 步 × 2 My = 250 My）</span></div>
          <div>dreamulator terrain generate earth -p earth -b terrain-dev -n 100000 --tectonic-steps 125</div>
          <div className="mt-2"><span className="text-gray-500"># 启动服务</span></div>
          <div>dreamulator serve --open</div>
          <div className="mt-2"><span className="text-gray-500"># 更多帮助</span></div>
          <div>dreamulator --help</div>
          <div>dreamulator terrain generate --help</div>
        </div>
      </section>

      {/* --- Map Controls --- */}
      <section>
        <h2 className="text-lg font-bold text-neon-cyan mb-3">地图操作</h2>
        <div className="grid grid-cols-2 gap-3 text-sm">
          {[
            ['拖拽', '平移地图'],
            ['滚轮', '缩放'],
            ['悬停 cell', '右侧面板显示属性'],
            ['双击 cell', '选中（Shift 多选）'],
            ['Ctrl + 双击', '切换选中'],
          ].map(([key, desc]) => (
            <div key={key} className="flex gap-2 bg-space-surface rounded px-3 py-2">
              <span className="text-neon-cyan font-mono shrink-0">{key}</span>
              <span className="text-gray-400">{desc}</span>
            </div>
          ))}
        </div>
      </section>

      {/* --- Layers --- */}
      <section>
        <h2 className="text-lg font-bold text-neon-cyan mb-3">图层说明</h2>
        <div className="space-y-2 text-sm">
          {[
            ['地形', '自适应海拔着色 — 默认开启。从深海蓝到高山白，基于 hypsometric tint。'],
            ['海陆', '二值蓝/绿着色 — 快速区分海洋和陆地。'],
            ['板块', '按构造板块着色 — 每种颜色代表一个独立的构造板块。'],
            ['地壳与边界', '板块内部：大陆(褐) / 海洋(蓝)；边界：汇聚(红) / 离散(绿) / 转换(黄)。'],
          ].map(([name, desc]) => (
            <div key={name} className="bg-space-surface rounded-lg p-3">
              <span className="text-neon-cyan font-semibold">{name}</span>
              <span className="text-gray-500"> — {desc}</span>
            </div>
          ))}
        </div>
      </section>

      {/* --- Concepts --- */}
      <section>
        <h2 className="text-lg font-bold text-neon-cyan mb-3">核心概念</h2>

        <div className="space-y-4">
          <div className="bg-space-surface rounded-lg p-4">
            <h3 className="text-gray-200 font-semibold mb-1">DAG 层级架构</h3>
            <p className="text-sm text-gray-500">
              世界数据按学科层级组织：physics → chemistry → astronomy → geological →
              climate → ecology → civilization。上游层级的输入决定下游层级的输出，
              形成有向无环图（DAG）推演管线。
            </p>
          </div>

          <div className="bg-space-surface rounded-lg p-4">
            <h3 className="text-gray-200 font-semibold mb-1">分支系统</h3>
            <p className="text-sm text-gray-500">
              类似 Git branch。在某一 DAG 层分叉，共享上层数据，仅存储分叉层及之后的数据。
              同一行星的不同分支可以有不同的海陆分布、气候或文明演化。
            </p>
          </div>

          <div className="bg-space-surface rounded-lg p-4">
            <h3 className="text-gray-200 font-semibold mb-1">CVT 球面网格</h3>
            <p className="text-sm text-gray-500">
              Centroidal Voronoi Tessellation — 使用 Fibonacci 螺旋 + Lloyd 松弛
              生成的球面均匀网格。所有模拟（构造、气候、水文）直接在球面网格上运行，
              仅在最终可视化时投影为 2D 栅格。
            </p>
          </div>

          <div className="bg-space-surface rounded-lg p-4">
            <h3 className="text-gray-200 font-semibold mb-1">Cortial 2019 板块构造</h3>
            <p className="text-sm text-gray-500">
              板块剖分和时间演化遵循 Cortial et al. (2019) <em>Procedural Tectonic
              Planets</em> 的方法：Poisson-disc 种子 → 球面 Voronoi 剖分 → Euler
              极旋转 → 边界重检测 → 俯冲/碰撞/侵蚀。
            </p>
          </div>
        </div>
      </section>

      {/* --- Docs links --- */}
      <section>
        <h2 className="text-lg font-bold text-neon-cyan mb-3">更多文档</h2>
        <ul className="space-y-1 text-sm text-gray-400">
          <li>📄 <span className="text-gray-300">docs/usage/cli.md</span> — CLI 命令参考</li>
          <li>📄 <span className="text-gray-300">docs/usage/terrain-pipeline.md</span> — 地形管线技术参考</li>
          <li>📄 <span className="text-gray-300">docs/design/roadmap-analysis.md</span> — 开发路线图</li>
          <li>📄 <span className="text-gray-300">docs/design/vision.md</span> — 项目长期愿景</li>
        </ul>
      </section>
    </div>
  )
}
