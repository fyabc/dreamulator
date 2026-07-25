/**
 * HelpPanel — slide-out help reference for the map viewer.
 *
 * TODO: full searchable help system with Markdown rendering.
 * For now, shows a quick-reference card with keyboard shortcuts
 * and layer descriptions.
 */

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
            <li><b className="text-gray-300">地形</b> — 自适应海拔着色（默认开启）</li>
            <li><b className="text-gray-300">海陆</b> — 二值蓝/绿着色</li>
            <li><b className="text-gray-300">板块</b> — 按构造板块着色</li>
            <li><b className="text-gray-300">地壳与边界</b> — 大陆(褐)/海洋(蓝) + 汇聚(红)/离散(绿)/转换(黄)</li>
          </ul>
        </section>

        <section>
          <h3 className="text-gray-400 font-semibold mb-1">操作</h3>
          <ul className="space-y-1 text-gray-500">
            <li><b className="text-gray-300">拖拽</b> — 平移地图</li>
            <li><b className="text-gray-300">滚轮</b> — 缩放</li>
            <li><b className="text-gray-300">悬停</b> — 查看 cell 详情（右侧面板）</li>
            <li><b className="text-gray-300">双击</b> — 选中 cell（Shift+双击多选）</li>
            <li><b className="text-gray-300">Ctrl+双击</b> — 切换选中</li>
          </ul>
        </section>

        <section>
          <h3 className="text-gray-400 font-semibold mb-1">分支</h3>
          <p className="text-gray-500">
            分支类似于 Git branch——在某一 DAG 层分叉，共享上层数据，仅存储分叉层及之后的数据。
            切换分支查看同一行星在不同构造/气候假设下的演化。
          </p>
        </section>

        <section>
          <h3 className="text-gray-400 font-semibold mb-1">投影</h3>
          <ul className="space-y-1 text-gray-500">
            <li><b className="text-gray-300">等距圆柱</b> — 经纬线正交，极区拉伸</li>
            <li><b className="text-gray-300">摩尔威德</b> — 等面积，椭圆外形</li>
            <li><b className="text-gray-300">罗宾逊</b> — 折中方案，视觉舒适</li>
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
