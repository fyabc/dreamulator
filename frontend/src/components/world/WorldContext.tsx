import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import { listProjects, projectsKey, worldOverviewPath } from '../../projects/projectStore'
import type { WorldScope } from './useWorldScope'

const controlClass = 'min-w-0 w-full truncate rounded border border-space-border bg-space-surface px-1.5 py-0.5 text-slate-100 hover:border-neon-cyan/50 focus-visible:outline focus-visible:outline-neon-cyan'

export default function WorldContext({ scope, className = '' }: {
  scope: WorldScope
  className?: string
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { pathname, search } = useLocation()
  const catalog = useQuery({ queryKey: ['worlds'], queryFn: api.listWorlds })
  const projects = useQuery({ queryKey: projectsKey, queryFn: listProjects, enabled: isStaticMode(), retry: false })
  const branches = useQuery({ queryKey: ['branches', scope.id], queryFn: () => api.listBranches(scope.id),
    enabled: !scope.browserWorld, retry: false })
  const worlds = new Map<string, string>(catalog.data?.map(id => [id, id]))
  for (const project of projects.data ?? []) {
    if (!project.published && !worlds.has(project.id)) worlds.set(project.id, project.name)
  }
  worlds.set(scope.id, scope.name)
  const branchName = scope.branch ?? t('context.base')
  const branchOptions = new Map((branches.data ?? []).map(item => [item.name, item.description]))
  if (scope.branch && !branchOptions.has(scope.branch)) branchOptions.set(scope.branch, undefined)

  const changeBranch = (branch: string) => {
    const next = new URLSearchParams(search)
    let target = pathname
    const overview = worldOverviewPath(scope.id)
    if (pathname === '/packs' && (next.has('project') || !next.has('world') || !next.has('window'))) {
      navigate(`${overview}${branch ? `?${new URLSearchParams({ branch })}` : ''}`)
      return
    }
    if (pathname.startsWith(`${overview}/civmap`)) {
      navigate(`${overview}/civmap${branch ? `/${encodeURIComponent(branch)}` : ''}`)
      return
    }
    if (pathname.startsWith(`${overview}/sky`)) {
      target = `${overview}/sky`
      next.delete('from')
    }
    for (const key of ['draft', 'climateResult', 'trial', 'pack', 'doc', 'layer', 'focus']) next.delete(key)
    if (branch) next.set('branch', branch)
    else next.delete('branch')
    navigate({ pathname: target, search: next.toString() })
  }

  return <div role="group" aria-label={t('context.label')} data-world-context
    className={`flex min-w-0 items-center gap-2 text-xs ${className}`}>
    <label className="flex min-w-0 items-center gap-1.5" title={scope.name}>
      <span className="shrink-0 text-slate-400">{t('context.world')}</span>
      {worlds.size > 1 ? <select aria-label={t('context.switchWorld')} className={controlClass}
        value={scope.id} onChange={event => navigate(worldOverviewPath(event.target.value))}>
        {[...worlds].map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select> : <strong className="truncate font-semibold text-slate-100">{scope.name}</strong>}
    </label>
    <span aria-hidden="true" className="h-3 shrink-0 border-l border-space-border" />
    <label className="flex min-w-0 items-center gap-1.5" title={scope.branch ? branchOptions.get(scope.branch) || branchName : branchName}>
      <span className="shrink-0 text-slate-400">{t('context.branch')}</span>
      {branchOptions.size > 0 ? <select aria-label={t('context.switchBranch')} className={controlClass}
        value={scope.branch ?? ''} onChange={event => changeBranch(event.target.value)}>
        <option value="">{t('context.base')}</option>
        {[...branchOptions.keys()].map(name => <option key={name} value={name}>{name}</option>)}
      </select> : <span className="truncate text-slate-200">{branchName}</span>}
    </label>
  </div>
}
