import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

interface BranchSelectorProps {
  worldName: string
  selectedBranch: string | null
  onSelect: (branch: string | null) => void
}

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

export default function BranchSelector({
  worldName,
  selectedBranch,
  onSelect,
}: BranchSelectorProps) {
  const { data: branches } = useQuery({
    queryKey: ['branches', worldName],
    queryFn: () => api.listBranches(worldName),
    enabled: !!worldName,
  })

  const selectedMeta = branches?.find((b) => b.name === selectedBranch)

  if (!branches || branches.length === 0) {
    return null
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-3">
        <label className="text-sm text-gray-500">分支</label>
        <select
          value={selectedBranch ?? ''}
          onChange={(e) => onSelect(e.target.value || null)}
          className="bg-space-bg border border-space-border rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-neon-cyan transition-colors"
        >
          <option value="">基础世界</option>
          {branches.map((b) => (
            <option key={b.name} value={b.name}>
              {b.name}
              {b.fork_layer
                ? `（${LAYER_LABELS[b.fork_layer] ?? b.fork_layer} 分叉）`
                : ''}
            </option>
          ))}
        </select>
      </div>

      {selectedMeta && (
        <div className="text-sm text-gray-400 flex flex-wrap gap-x-4">
          <span>
            <span className="text-gray-600">分叉层：</span>
            {LAYER_LABELS[selectedMeta.fork_layer] ?? selectedMeta.fork_layer}
          </span>
          {selectedMeta.description && (
            <span>
              <span className="text-gray-600">描述：</span>
              {selectedMeta.description}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
