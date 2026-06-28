/**
 * MapEditingTools — brush tool controls for heightmap editing.
 *
 * NOTE: Brush painting is not yet wired to the map canvas. The tool UI
 * is displayed with a "coming soon" overlay to indicate planned features.
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
  onChange: _onChange,
  onGenerate,
  onSave,
  isGenerating,
  isSaving,
  hasUnsavedChanges,
}: MapEditingToolsProps) {
  return (
    <div className="space-y-4">
      {/* Brush tools — coming soon */}
      <div className="relative">
        <div className="flex items-center gap-2 mb-2">
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            工具
          </h3>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/30 text-amber-400 border border-amber-700/30">
            即将推出
          </span>
        </div>

        <div className="opacity-40 pointer-events-none">
          <div className="grid grid-cols-5 gap-1">
            {TOOLS.map((tool) => (
              <button
                key={tool.id}
                disabled
                className="flex flex-col items-center gap-0.5 p-1.5 rounded text-xs bg-space-surface/60 text-gray-400 border border-transparent"
                title={`${tool.label}（即将推出）`}
              >
                <span className="text-sm">{tool.icon}</span>
                <span className="text-[10px]">{tool.label}</span>
              </button>
            ))}
          </div>

          {/* Brush settings (disabled) */}
          <div className="mt-2">
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              画笔设置
            </h3>
            <div className="space-y-2">
              <div>
                <label className="text-xs text-gray-400 flex justify-between">
                  <span>大小</span>
                  <span className="font-mono">{config.radius}px</span>
                </label>
                <input type="range" disabled min={2} max={100} value={config.radius} className="w-full h-1 accent-neon-cyan" />
              </div>
              <div>
                <label className="text-xs text-gray-400 flex justify-between">
                  <span>强度</span>
                  <span className="font-mono">{Math.round(config.strength * 100)}%</span>
                </label>
                <input type="range" disabled min={1} max={100} value={Math.round(config.strength * 100)} className="w-full h-1 accent-neon-cyan" />
              </div>
              <div>
                <label className="text-xs text-gray-400 flex justify-between">
                  <span>硬度</span>
                  <span className="font-mono">{Math.round(config.hardness * 100)}%</span>
                </label>
                <input type="range" disabled min={0} max={100} value={Math.round(config.hardness * 100)} className="w-full h-1 accent-neon-cyan" />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="pt-2 border-t border-space-border space-y-2">
        <div>
          <button
            onClick={onGenerate}
            disabled={isGenerating}
            className="w-full px-3 py-2 rounded-lg text-sm font-medium bg-space-surface/60 text-gray-300 border border-space-border hover:border-neon-cyan/30 transition-colors disabled:opacity-50"
            title="使用默认参数程序化生成地形（3 大陆 / 0.5 山脉度 / 15 板块）"
          >
            {isGenerating ? '生成中...' : '🌍 生成地形'}
          </button>
          <p className="text-[10px] text-gray-600 mt-1 text-center">
            当前使用固定参数，可调节参数即将推出
          </p>
        </div>
        <button
          onClick={onSave}
          disabled={isSaving || !hasUnsavedChanges}
          className="w-full px-3 py-2 rounded-lg text-sm font-medium bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 transition-colors disabled:opacity-50"
          title="将编辑后的高度图上传保存到后端"
        >
          {isSaving ? '保存中...' : hasUnsavedChanges ? '💾 保存修改' : '已保存'}
        </button>
      </div>
    </div>
  )
}
