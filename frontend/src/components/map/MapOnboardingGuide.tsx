/**
 * MapOnboardingGuide — first-time onboarding overlay for the map editor.
 *
 * Shows a concise overview of the editor layout and available features.
 * Dismissal is remembered in localStorage. Can be reopened via the
 * "?" help button in the top bar.
 */

interface MapOnboardingGuideProps {
  onClose: () => void
}

const STORAGE_KEY = 'dreamulator:map-onboarding-dismissed'

export function isOnboardingDismissed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

export function dismissOnboarding(): void {
  try {
    localStorage.setItem(STORAGE_KEY, 'true')
  } catch {
    // Ignore storage errors (e.g. private browsing)
  }
}

export function resetOnboarding(): void {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Ignore
  }
}

export default function MapOnboardingGuide({ onClose }: MapOnboardingGuideProps) {
  const handleClose = () => {
    dismissOnboarding()
    onClose()
  }

  return (
    <div
      className="absolute inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={handleClose}
    >
      <div
        className="relative max-w-lg w-full mx-4 bg-space-panel border border-space-border rounded-xl shadow-2xl p-6"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Close button */}
        <button
          onClick={handleClose}
          className="absolute top-3 right-3 text-gray-500 hover:text-gray-300 transition-colors text-lg"
          aria-label="关闭"
        >
          ✕
        </button>

        <h2 className="text-lg font-bold text-neon-cyan mb-1">🗺️ 地图编辑器</h2>
        <p className="text-xs text-gray-500 mb-4">
          查看和探索行星地形。以下是编辑器的各区域介绍。
        </p>

        {/* Layout diagram */}
        <div className="bg-space-surface/40 rounded-lg p-3 mb-4 text-xs font-mono text-gray-400 leading-relaxed border border-space-border/50">
          <div className="text-gray-500 mb-1">┌─────────────────────────────────┐</div>
          <div className="text-gray-500">│{' '}<span className="text-neon-cyan">顶栏</span>：行星选择 · 分支 · 帮助{'  '}│</div>
          <div className="text-gray-500">├────────┬──────────┬───────────┤</div>
          <div className="text-gray-500">│{' '}<span className="text-amber-300">左面板</span>{' '}│{'  '}<span className="text-green-300">地图视图</span>{'  '}│{' '}<span className="text-blue-300">右面板</span>{' '}│</div>
          <div className="text-gray-500">│ 图层   │  Three.js │  单元格   │</div>
          <div className="text-gray-500">│ 工具   │  + SVG    │  详情     │</div>
          <div className="text-gray-500">├────────┴──────────┴───────────┤</div>
          <div className="text-gray-500">│{' '}<span className="text-gray-300">底栏</span>：经纬度 · 海拔 · 缩放{'     '}│</div>
          <div className="text-gray-500">└─────────────────────────────────┘</div>
        </div>

        {/* Feature list */}
        <div className="space-y-2 text-sm mb-4">
          <div className="flex items-start gap-2">
            <span className="text-green-400 shrink-0">✓</span>
            <div>
              <span className="text-gray-300">导航</span>
              <span className="text-gray-500"> — 拖拽平移，滚轮缩放</span>
            </div>
          </div>
          <div className="flex items-start gap-2">
            <span className="text-green-400 shrink-0">✓</span>
            <div>
              <span className="text-gray-300">着色模式</span>
              <span className="text-gray-500"> — 地形 / 海拔 / 海陆 / 坡度</span>
            </div>
          </div>
          <div className="flex items-start gap-2">
            <span className="text-green-400 shrink-0">✓</span>
            <div>
              <span className="text-gray-300">矢量叠加</span>
              <span className="text-gray-500"> — Voronoi 网格 / 板块边界 / 河流</span>
            </div>
          </div>
          <div className="flex items-start gap-2">
            <span className="text-green-400 shrink-0">✓</span>
            <div>
              <span className="text-gray-300">程序化生成</span>
              <span className="text-gray-500"> — 一键生成地形 + Voronoi + 板块</span>
            </div>
          </div>
          <div className="flex items-start gap-2">
            <span className="text-amber-400 shrink-0">◌</span>
            <div>
              <span className="text-gray-500">画笔绘制 / 参数调节 / 选择操作</span>
              <span className="text-gray-600 text-xs ml-1">即将推出</span>
            </div>
          </div>
        </div>

        <button
          onClick={handleClose}
          className="w-full py-2 rounded-lg text-sm font-medium bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 transition-colors"
        >
          开始使用
        </button>

        <p className="text-center text-xs text-gray-600 mt-2">
          随时点击顶栏的 <span className="font-mono text-gray-400">?</span> 按钮重新查看
        </p>
      </div>
    </div>
  )
}
