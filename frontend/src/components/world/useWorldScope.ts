import { useQuery } from '@tanstack/react-query'
import { useMatch, useSearchParams } from 'react-router-dom'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import { elevationSource } from '../../projects/elevationProject'
import { getProject, projectKey } from '../../projects/projectStore'

export function useWorldScope() {
  const world = useMatch('/worlds/:worldName/*')?.params.worldName
  const civilizationBranch = useMatch('/worlds/:worldName/civmap/:branchName')?.params.branchName
  const inRegion = !!useMatch('/packs')
  const [search] = useSearchParams()
  const projectId = inRegion ? search.get('project') : null
  const pack = inRegion && !projectId && !search.has('world') ? search.get('pack') : null
  const packs = useQuery({ queryKey: ['packs'], queryFn: api.listPacks, enabled: !!pack && !isStaticMode(), retry: false })
  const origin = packs.data?.find(item => item.name === pack)
  const id = world ?? (inRegion ? projectId ?? search.get('world') ?? origin?.world : undefined)
  const project = useQuery({ queryKey: projectKey(id ?? ''), queryFn: () => getProject(id!),
    enabled: !!id && (isStaticMode() || !!projectId), retry: false })
  if (!id) return null
  const browserWorld = project.data && !project.data.published ? project.data : null
  const layer = projectId && project.data?.layers.find(item => item.id === search.get('layer'))
  const location = layer && elevationSource(project.data?.layers ?? [], layer)?.location
  const branch = location ? location.branch : browserWorld ? null : civilizationBranch ?? search.get('branch') ?? origin?.branch
  return { id, name: browserWorld?.name ?? id, branch: branch || null, browserWorld }
}

export type WorldScope = NonNullable<ReturnType<typeof useWorldScope>>
