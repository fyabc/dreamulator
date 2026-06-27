/**
 * MapEditingTools — brush tool controls for heightmap editing.
 */

import type { BrushConfig, EditTool } from '../../viewers/map/types'

interface MapEditingToolsProps {
  config: BrushConfig
  onChange: (config: BrushConfig) => void
  onGenerate: () => void
  onSave: () => void
  isGenerating: boolean
  isSaving: boolean
  hasUnsavedChanges: boolean
}

const TOOLS: { id: EditTool; label: string; icon: string }[] = [
  { id: 'raise', label: '升起', icon: '🔺' },
  { id: 'lower', label: '降低', icon: '🔻' },
  { id: 'smooth', label: '平滑', icon: '〰️' },
  { id: 'flatten', label: '平坦', icon: '━' },
  { id: 'select', label: '选择', icon: '🖱️' },
]

export default function MapEditingTools({
  config,
  onChange,
  onGenerate,
  onSave,
  isGenerating,
  isSaving,
  hasUnsavedChanges,
}: MapEditingToolsProps) {
  return (
    <div className="space-y-4">
      {/* Brush tools */}
      <div>
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
          工具
        </h3>
        <div className="grid grid-cols-5 gap-1">
          {TOOLS.map((tool) => (
            <button
              key={tool.id}
              onClick={() => onChange({ ...config, tool: tool.id })}
              className={`flex flex-col items-center gap-0.5 p-1.5 rounded text-xs transition-colors ${
                config.tool === tool.id
                  ? 'bg-neon-cyan/20 text-neon-cyan border border-neon-cyan/40'
                  : 'bg-space-surface/60 text-gray-400 border border-transparent hover:border-space-border'
              }`}
              title={tool.label}
            >
              <span className="text-sm">{tool.icon}</span>
              <span className="text-[10px]">{tool.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Brush settings */}
      {config.tool !== 'select' && (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            画笔设置
          </h3>
          <div className="space-y-2">
            <div>
              <label className="text-xs text-gray-400 flex justify-between">
                <span>大小</span>
                <span className="font-mono">{config.radius}px</span>
              </label>
              <input
                type="range"
                min={2}
                max={100}
                value={config.radius}
                onChange={(e) =>
                  onChange({ ...config, radius: parseInt(e.target.value) })
                }
                className="w-full h-1 accent-neon-cyan"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 flex justify-between">
                <span>强度</span>
                <span className="font-mono">{Math.round(config.strength * 100)}%</span>
              </label>
              <input
                type="range"
                min={1}
                max={100}
                value={Math.round(config.strength * 100)}
                onChange={(e) =>
                  onChange({ ...config, strength: parseInt(e.target.value) / 100 })
                }
                className="w-full h-1 accent-neon-cyan"
              />
            </div>
            <div>
              <label className="text-xs text-gray-400 flex justify-between">
                <span>硬度</span>
                <span className="font-mono">{Math.round(config.hardness * 100)}%</span>
              </label>
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round(config.hardness * 100)}
                onChange={(e) =>
                  onChange({ ...config, hardness: parseInt(e.target.value) / 100 })
                }
                className="w-full h-1 accent-neon-cyan"
              />
            </div>
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="pt-2 border-t border-space-border space-y-2">
        <button
          onClick={onGenerate}
          disabled={isGenerating}
          className="w-full px-3 py-2 rounded-lg text-sm font-medium bg-space-surface/60 text-gray-300 border border-space-border hover:border-neon-cyan/30 transition-colors disabled:opacity-50"
        >
          {isGenerating ? '生成中...' : '🌍 生成地形'}
        </button>
        <button
          onClick={onSave}
          disabled={isSaving || !hasUnsavedChanges}
          className="w-full px-3 py-2 rounded-lg text-sm font-medium bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 transition-colors disabled:opacity-50"
        >
          {isSaving ? '保存中...' : hasUnsavedChanges ? '💾 保存修改' : '已保存'}
        </button>
      </div>
    </div>
  )
}
