import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'

interface BranchSelectorProps {
  worldName: string
  selectedBranch: string | null
  onSelect: (branch: string | null) => void
}

const LAYER_LABELS: Record<string, string> = {
  physics: 'layer.physics',
  chemistry: 'layer.chemistry',
  astronomy: 'layer.astronomy',
  geological: 'layer.geological',
  climate: 'layer.climate',
  ecology: 'layer.ecology',
  civilization: 'layer.civilization',
}

export default function BranchSelector({
  worldName,
  selectedBranch,
  onSelect,
}: BranchSelectorProps) {
  const { t } = useTranslation('worlds')
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
        <label htmlFor="branch-select" className="text-sm text-gray-500">{t('branch.label')}</label>
        <select
          id="branch-select"
          value={selectedBranch ?? ''}
          onChange={(e) => onSelect(e.target.value || null)}
          className="bg-space-bg border border-space-border rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-neon-cyan transition-colors"
          aria-label={t('label.selectBranch')}
          title={t('branch.hint')}
        >
          <option value="">{t('label.baseWorld')}</option>
          {branches.map((b) => (
            <option key={b.name} value={b.name}>
              {b.name}
              {b.fork_layer
                ? t('label.forkedAt', { layer: t(LAYER_LABELS[b.fork_layer] ?? b.fork_layer) })
                : ''}
            </option>
          ))}
        </select>
      </div>

      {selectedMeta && (
        <div className="text-sm text-gray-400 flex flex-wrap items-start gap-x-4">
          <span className="shrink-0">
            <span className="text-gray-600">{t('branch.forkLayer')}</span>
            {t(LAYER_LABELS[selectedMeta.fork_layer] ?? selectedMeta.fork_layer)}
          </span>
          {selectedMeta.description && (
            <span
              className="truncate max-w-[240px]"
              title={selectedMeta.description}
            >
              <span className="text-gray-600">{t('branch.description')}</span>
              {selectedMeta.description}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
