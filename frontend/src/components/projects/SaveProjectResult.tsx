import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { makeElevationResult, makeElevationSource, type ElevationFrame } from '../../projects/elevationProject'
import { projectRegionPath, projectsKey, publishedWorld, updateProject } from '../../projects/projectStore'
import { tutorialMilestone } from '../../tutorial/tutorialProgress'
import type { BrowserTerrainResult } from '../../viewers/packs/TerrainCompute'
import type { ElevationRaster } from '../../viewers/packs/elevationRaster'

export const projectButton = 'rounded border border-space-border bg-space-surface px-2 py-1 text-neon-cyan disabled:opacity-50'
export const projectField = 'min-w-0 rounded border border-space-border bg-space-bg px-2 py-1 text-gray-200'

type Target = { worldId: string } & ({ sourceId: string; branch?: string | null } | {
  planet: string; branch: string | null; sourceName: string; raster: ElevationRaster; frame: ElevationFrame;
  browserWorld?: true; climateResult?: string
})

export default function SaveProjectResult({ target, result }: { target: Target; result: BrowserTerrainResult }) {
  const { t } = useTranslation('worlds', { keyPrefix: 'worldData' })
  const queryClient = useQueryClient()
  const save = useMutation({ mutationFn: async (current: BrowserTerrainResult) => {
    const input = 'sourceId' in target ? null : { ...makeElevationSource(target.sourceName, target.raster, target.frame),
      location: { planet: target.planet, branch: target.branch, ...(target.climateResult && { climateResult: target.climateResult }) } }
    const sourceId = 'sourceId' in target ? target.sourceId : input!.id
    const output = makeElevationResult(t(`layer.${current.recipe.method}`), sourceId, current)
    const initial = input && !('browserWorld' in target && target.browserWorld) ? publishedWorld(target.worldId) : undefined
    await updateProject(target.worldId, (world) => {
      if (!input && !world.layers.some((layer) => layer.kind === 'elevation-source' && layer.id === sourceId)) throw new Error('Source is missing')
      return { ...world, layers: input ? [...world.layers, input, output] : [...world.layers, output] }
    }, initial)
    return output.id
  }, onSuccess: () => {
    void queryClient.invalidateQueries({ queryKey: projectsKey })
    if ('planet' in target && target.browserWorld) {
      tutorialMilestone({ type: 'regionResult', world: target.worldId, planet: target.planet, branch: target.branch })
    }
  } })

  if (save.isSuccess && save.variables === result) return <p role="status">
    {t('saved')} <Link className={projectButton} to={projectRegionPath(target.worldId, save.data, target.branch)}>{t('openSaved')}</Link>
  </p>
  return <div className="space-y-2 border-t border-space-border pt-2">
    <p role="status">{t('unsaved')}</p>
    <button type="button" className={projectButton} data-tutorial-anchor="browserSave" onClick={() => save.mutate(result)}
      disabled={save.isPending}>{t(save.isPending ? 'saving' : 'save')}</button>
    {save.isError && <p role="alert" className="text-red-300">{t('saveFailed')}</p>}
  </div>
}
