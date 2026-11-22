import { useId, type ReactNode } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import type { WorldParameters } from '../../api/worldParameters'

export const buildPrimaryAction = 'min-h-11 rounded-lg border border-neon-cyan/30 bg-neon-cyan/15 px-4 py-2 font-medium text-neon-cyan hover:bg-neon-cyan/25 focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan disabled:opacity-50'
export const buildSecondaryAction = 'inline-flex min-h-11 items-center rounded text-sm font-medium text-gray-200 underline decoration-gray-500 underline-offset-4 hover:text-neon-cyan focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan'

export default function WorldBuildCard({ branch, summary, backup, checkSettings, checkHelp, actions, savedMap,
  visible = true, buildingAnchor, children }: {
  branch: string | null
  summary?: ReactNode
  backup?: ReactNode
  checkSettings: () => Promise<{ ok: boolean; errors: string[] }>
  checkHelp?: string
  actions?: ReactNode
  savedMap?: { cells?: number; savedAt?: string }
  visible?: boolean
  buildingAnchor?: boolean
  children?: ReactNode
}) {
  const { t, i18n } = useTranslation('worlds')
  const title = useId()
  const validation = useMutation({ mutationFn: checkSettings })
  return <section id="build" hidden={!visible} data-tutorial-anchor={buildingAnchor ? 'building' : undefined}
    className="glass-panel mb-4 space-y-3 p-4" aria-labelledby={title}>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0">
        <h2 id={title} className="font-semibold text-neon-cyan">{t('build.title')}</h2>
        <p className="text-sm text-gray-400">{t('build.target', { branch: branch ?? t('label.baseWorld') })}</p>
        {summary}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {backup}
        <button type="button" className={`${buildSecondaryAction} disabled:text-gray-400 disabled:no-underline`}
          title={checkHelp ?? t('build.validateSettingsHelp')} onClick={() => validation.mutate()} disabled={validation.isPending}>
          {t(validation.isPending ? 'build.validating' : 'build.validateSettings')}
        </button>
        {actions}
      </div>
    </div>
    {validation.isError ? <p role="alert" className="break-words text-sm text-red-300">
      {t('build.validationError', { error: validation.error.message })}
    </p> : validation.data && !validation.isPending && <div role="status" className={`text-sm ${validation.data.ok ? 'text-green-300' : 'text-red-300'}`}>
      <p>{t(validation.data.ok ? 'build.validationPassed' : 'build.validationFailed')}</p>
      {validation.data.errors.length > 0 && <ul className="list-disc break-words pl-5">
        {validation.data.errors.map((error, index) => <li key={index}>{error}</li>)}
      </ul>}
    </div>}
    {children}
    {savedMap && <p className="text-sm text-gray-400">
      {t('build.savedMap')}
      {savedMap.cells != null && <> · {t('build.savedGrid', { cells: savedMap.cells.toLocaleString(i18n.resolvedLanguage) })}</>}
      {savedMap.savedAt && <> · <time dateTime={savedMap.savedAt}>
        {new Date(savedMap.savedAt).toLocaleString(i18n.resolvedLanguage, { dateStyle: 'medium', timeStyle: 'short' })}
      </time></>}
    </p>}
  </section>
}

export function WorldBuildGridStatus({ grid, loading, builtCells = grid?.built_cells }: {
  grid?: WorldParameters
  loading: boolean
  builtCells?: number | null
}) {
  const { t, i18n } = useTranslation('worlds')
  const cells = grid?.num_cells?.toLocaleString(i18n.resolvedLanguage)
  const needsRebuild = grid?.planet?.needs_rebuild ||
    (grid && !grid.reuses_mesh && builtCells != null && grid.num_cells != null && builtCells !== grid.num_cells)
  const label = loading ? t('build.gridLoading') : cells != null
    ? t(grid?.reuses_mesh ? 'build.gridReused' : 'build.gridConfigured', { cells })
    : t(grid?.reuses_mesh ? 'build.gridReusedUnknown' : 'build.gridUnknown')
  return <>
    <p className="text-sm text-gray-400" role="status">{label}</p>
    {needsRebuild && <p role="status" className="text-sm text-amber-200">{t('parameters.rebuild')}</p>}
  </>
}

export function WorldBuildStageDetails({ running, titleId, children }: {
  running: boolean
  titleId?: string
  children: ReactNode
}) {
  const { t } = useTranslation('worlds')
  return <details open={running} className="space-y-2 border-t border-space-border pt-2 text-sm">
    <summary id={titleId} className="w-fit cursor-pointer rounded text-gray-300 hover:text-neon-cyan focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan">
      {t('build.stageDetails')}
    </summary>
    {children}
  </details>
}
