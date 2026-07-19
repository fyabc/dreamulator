/**
 * MapTools — import/export actions for the map editor.
 *
 * The map editor focuses on visualization, not in-app terrain editing.
 * Terrain design is done in external tools (Gaea, World Machine, etc.)
 * and imported as heightmaps.
 */

interface MapToolsProps {
  onImport: () => void
  isImporting: boolean
  hasElevation: boolean
}

export default function MapTools({
  onImport,
  isImporting,
  hasElevation,
}: MapToolsProps) {
  return (
    <div className="space-y-3">
      {/* Import / Export actions */}
      <div className="space-y-2">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          数据操作
        </h3>

        <button
          onClick={onImport}
          disabled={isImporting}
          className="w-full px-3 py-2 rounded-lg text-sm font-medium bg-space-surface/60 text-gray-300 border border-space-border hover:border-neon-cyan/30 transition-colors disabled:opacity-50"
          title="从外部工具（Gaea, World Machine 等）导入 16-bit 高度图（PNG/TIFF）"
        >
          {isImporting ? '导入中...' : '📥 导入高度图'}
        </button>

        {hasElevation && (
          <button
            disabled
            className="w-full px-3 py-2 rounded-lg text-sm font-medium bg-space-surface/60 text-gray-400 border border-space-border opacity-40 pointer-events-none"
            title="将 Voronoi 网格导出为 GeoJSON 政区边界（即将推出）"
          >
            📤 导出 GeoJSON
            <span className="block text-[10px] text-gray-600 mt-0.5">即将推出</span>
          </button>
        )}
      </div>

      {/* Info */}
      <div className="pt-2 border-t border-space-border">
        <p className="text-[10px] text-gray-600 leading-relaxed">
          地形设计请在{' '}
          <a
            href="https://quadspinner.com/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-gray-500 hover:text-neon-cyan underline"
          >
            Gaea
          </a>{' '}
          等外部工具中完成，导出 16-bit TIFF 后导入 Dreamulator。
        </p>
      </div>
    </div>
  )
}
