/**
 * HelpPage — global reference page accessible from sidebar "?".
 *
 * Covers: project concepts, map controls, CLI quick-start, layers,
 * and links to full documentation.
 *
 * TODO: searchable, Markdown-rendered help system.
 */

import { LAYER_HELP, CONTROL_HELP, CONCEPT_HELP } from '../components/map/helpContent'

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
          {CONTROL_HELP.map((c) => (
            <div key={c.action} className="flex gap-2 bg-space-surface rounded px-3 py-2">
              <span className="text-neon-cyan font-mono shrink-0">{c.action}</span>
              <span className="text-gray-400">{c.description}</span>
            </div>
          ))}
        </div>
      </section>

      {/* --- Layers --- */}
      <section>
        <h2 className="text-lg font-bold text-neon-cyan mb-3">图层说明</h2>
        <div className="space-y-2 text-sm">
          {LAYER_HELP.map((l) => (
            <div key={l.id} className="bg-space-surface rounded-lg p-3">
              <span className="text-neon-cyan font-semibold">{l.label}</span>
              <span className="text-gray-500"> — {l.detail}</span>
            </div>
          ))}
        </div>
      </section>

      {/* --- Concepts --- */}
      <section>
        <h2 className="text-lg font-bold text-neon-cyan mb-3">核心概念</h2>
        <div className="space-y-4">
          {CONCEPT_HELP.map((c) => (
            <div key={c.title} className="bg-space-surface rounded-lg p-4">
              <h3 className="text-gray-200 font-semibold mb-1">{c.title}</h3>
              <p className="text-sm text-gray-500">{c.summary}</p>
            </div>
          ))}
        </div>
      </section>

      {/* --- Docs links --- */}
      <section>
        <h2 className="text-lg font-bold text-neon-cyan mb-3">更多文档</h2>
        <ul className="space-y-1 text-sm text-gray-400">
          <li>📄 <span className="text-gray-300">docs/usage/cli.md</span> — CLI 命令参考</li>
          <li>📄 <span className="text-gray-300">docs/design/terrain-pipeline.md</span> — 地形管线技术参考</li>
          <li>📄 <span className="text-gray-300">docs/design/roadmap.md</span> — 开发路线图</li>
          <li>📄 <span className="text-gray-300">docs/design/vision.md</span> — 项目长期愿景</li>
        </ul>
      </section>
    </div>
  )
}
