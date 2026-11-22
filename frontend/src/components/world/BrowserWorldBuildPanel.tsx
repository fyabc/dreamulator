import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { savedClimateKey, type ClimateTrialJob } from '../../api/climateTrials'
import { worldParametersKey } from '../../api/worldParameters'
import { EbmTrialProgress } from '../../playground/EbmTrialProgress'
import { hasProjectHeightmap, type LocalProject } from '../../projects/elevationProject'
import { heightmapPlanet, latestHeightmapClimate } from '../../projects/heightmapWorld'
import { projectsKey } from '../../projects/projectStore'
import { downloadWorldBackup } from '../../projects/worldDataArchive'
import { tutorialMilestone } from '../../tutorial/tutorialProgress'
import WorldBuildCard, { buildPrimaryAction, buildSecondaryAction, WorldBuildGridStatus, WorldBuildStageDetails } from './WorldBuildCard'

export default function BrowserWorldBuildPanel({ project, visible }: { project: LocalProject; visible: boolean }) {
  const { t, i18n } = useTranslation(['worlds', 'playground'])
  const queryClient = useQueryClient()
  const controller = useRef<AbortController | null>(null)
  const [job, setJob] = useState<ClimateTrialJob>()
  const [phase, setPhase] = useState<string>()
  const [cancelled, setCancelled] = useState(false)
  const hasMap = hasProjectHeightmap(project)
  const archive = project.creationSnapshot
  const grid = useQuery({ queryKey: worldParametersKey(project.id, null), queryFn: () => api.getWorldParameters(project.id, null),
    enabled: hasMap && visible, retry: false })
  const backup = useMutation({ mutationFn: async () => downloadWorldBackup(project),
    onSuccess: () => { if (archive) tutorialMilestone({ type: 'backup', world: project.id }) } })
  const checkSettings = async () => {
    if (!archive) throw new Error(t('browserBuild.noSettings'))
    const { readCreationSnapshot } = await import('../../projects/creationSnapshot')
    const snapshot = await readCreationSnapshot(archive)
    if (project.creationKind === 'starter') {
      const { readStarterSnapshot } = await import('../../projects/starterWorld')
      await readStarterSnapshot(snapshot)
    } else {
      const { readHeightmapSnapshot } = await import('../../projects/heightmapWorld')
      await readHeightmapSnapshot(snapshot)
    }
    return { ok: true, errors: [] }
  }
  useEffect(() => () => controller.current?.abort(), [])
  const build = useMutation({ mutationFn: async () => {
    const run = new AbortController()
    controller.current = run
    setJob(undefined)
    setCancelled(false)
    setPhase('queued')
    try {
      let current = await api.startClimateTrial(project.id, heightmapPlanet, null, {}, run.signal)
      while (!run.signal.aborted) {
        setJob(current)
        setPhase(current.stage)
        if (current.state === 'failed') throw new Error(current.error ?? 'browser_run')
        if (current.state === 'succeeded') {
          setPhase('saving')
          const result = await api.saveClimateTrial(project.id, heightmapPlanet, current.id, null)
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: projectsKey }),
            queryClient.invalidateQueries({ queryKey: savedClimateKey(project.id) }),
            queryClient.invalidateQueries({ queryKey: worldParametersKey(project.id, null) }),
          ])
          tutorialMilestone({ type: 'built', world: project.id })
          setPhase('done')
          return result
        }
        await new Promise(resolve => window.setTimeout(resolve, 400))
        run.signal.throwIfAborted()
        current = await api.getClimateTrial(project.id, heightmapPlanet, current.id, run.signal)
      }
      run.signal.throwIfAborted()
    } catch (error) {
      if (!run.signal.aborted) throw error
    } finally {
      run.abort()
      controller.current = null
    }
  } })
  const latest = latestHeightmapClimate(project)
  const format = new Intl.NumberFormat(i18n.language, { maximumFractionDigits: 0 })
  const reason = build.error?.message

  return <WorldBuildCard branch={null} visible={visible}
    summary={hasMap && <WorldBuildGridStatus grid={grid.data} loading={grid.isPending} builtCells={latest?.cells} />}
    savedMap={latest && { cells: latest.cells, savedAt: latest.saved_at }}
    checkSettings={checkSettings} checkHelp={t('browserBuild.checkHelp')}
    backup={<button type="button" className={`${buildSecondaryAction} disabled:text-gray-400 disabled:no-underline`}
      title={t(build.isPending ? 'build.snapshotAfterBuild' : 'browserBuild.backupScope')}
      disabled={build.isPending || backup.isPending} onClick={() => backup.mutate()}>{t('build.downloadSnapshot')}</button>}
    actions={<>
      {build.isPending && phase !== 'saving' && <button type="button" className={buildSecondaryAction} onClick={() => {
        setCancelled(true)
        controller.current?.abort()
      }}>{t('action.cancel')}</button>}
      <button type="button" disabled={!hasMap || build.isPending || grid.isPending} className={buildPrimaryAction}
        data-tutorial-anchor="browserBuild" title={t('browserBuild.scope')}
        onClick={() => build.mutate()}>{t(build.isError ? 'build.retry' : 'action.buildWorld')}</button>
    </>}>
    {!hasMap && <p className="text-sm text-gray-400">{t('browserBuild.noHeightmap')}</p>}
    {backup.isError && <p role="alert" className="text-sm text-red-300">{t('worldData.exportFailed')}</p>}
    {phase && <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
      <div className="space-y-1" role="status">
        {build.isPending && <p className="font-medium">{t(phase === 'saving' ? 'worldData.saving' : 'build.job.running')}</p>}
        {phase === 'done' && <p className="font-medium">{t('browserBuild.saved')}</p>}
        {cancelled && !build.isPending && <p className="text-gray-400">{t('browserBuild.cancelled')}</p>}
      </div>
      {job && !cancelled && <span className="text-gray-400">{t('build.elapsed', { seconds: Math.floor(job.elapsed_seconds) })}</span>}
    </div>}
    {build.isPending && phase !== 'saving' && <p className="text-sm text-gray-400">{t('browserBuild.keepOpen')}</p>}
    {reason && <p role="alert" className="break-words text-sm text-red-300">
      {t(`playground:ebm.error.${reason}`, { defaultValue: t(phase === 'saving' ? 'browserBuild.saveFailed' : 'browserBuild.failed') })}
    </p>}
    {phase && !cancelled && <WorldBuildStageDetails running={build.isPending}>
      <EbmTrialProgress phase={phase === 'saving' ? 'loading' : phase} job={job} interrupted={build.isError}
        open={visible && build.isPending} starting={false} browser format={format} embedded />
    </WorldBuildStageDetails>}
  </WorldBuildCard>
}
