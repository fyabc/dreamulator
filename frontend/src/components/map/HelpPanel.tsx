/**
 * HelpPanel — slide-out help reference for the map viewer.
 *
 * TODO: full searchable help system with Markdown rendering.
 *
 * Content is driven by the shared helpContent.ts module —
 * layer descriptions, controls, and projections stay in sync
 * with the UI automatically.
 */

import { LAYER_HELP, CONTROL_HELP, PROJECTION_HELP } from './helpContent'

interface HelpPanelProps {
  onClose: () => void
}

export default function HelpPanel({ onClose }: HelpPanelProps) {
  return (
    <div className="absolute right-0 top-0 bottom-0 w-72 bg-space-panel/95 border-l border-space-border z-50 overflow-y-auto p-4 shadow-xl backdrop-blur">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-bold text-neon-cyan">帮助</h2>
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-gray-300 text-lg leading-none"
          title="关闭帮助"
        >
          ✕
        </button>
      </div>

      {/* TODO banner */}
      <div className="mb-4 p-2 rounded bg-yellow-900/20 border border-yellow-700/30 text-xs text-yellow-300">
        🚧 完整帮助系统待实现。以下为快速参考。
      </div>

      {/* Quick reference */}
      <div className="space-y-4 text-xs">
        <section>
          <h3 className="text-gray-400 font-semibold mb-1">图层</h3>
          <ul className="space-y-1 text-gray-500">
            {LAYER_HELP.map((l) => (
              <li key={l.id}><b className="text-gray-300">{l.label}</b> — {l.desc}</li>
            ))}
          </ul>
        </section>

        <section>
          <h3 className="text-gray-400 font-semibold mb-1">操作</h3>
          <ul className="space-y-1 text-gray-500">
            {CONTROL_HELP.map((c) => (
              <li key={c.action}><b className="text-gray-300">{c.action}</b> — {c.description}</li>
            ))}
          </ul>
        </section>

        <section>
          <h3 className="text-gray-400 font-semibold mb-1">投影</h3>
          <ul className="space-y-1 text-gray-500">
            {PROJECTION_HELP.map((p) => (
              <li key={p.id}><b className="text-gray-300">{p.label}</b> — {p.description}</li>
            ))}
          </ul>
        </section>

        <section>
          <h3 className="text-gray-400 font-semibold mb-1">更多</h3>
          <p className="text-gray-500">
            完整文档见 <code className="text-gray-400">docs/usage/</code>
            {' '}和 CLI <code className="text-gray-400">--help</code>。
          </p>
        </section>
      </div>
    </div>
  )
}
