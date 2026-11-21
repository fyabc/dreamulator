import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { BuildJob } from '../../api/buildJobs'
import { worldParametersKey } from '../../api/worldParameters'
import { tutorialMilestone, useWorkflowTutorial } from '../../tutorial/tutorialProgress'
import WorldBuildProgress from './WorldBuildProgress'

interface WorldBuildPanelProps {
  world: string
  branch: string | null
  readOnly: boolean
}

function isActive(job: BuildJob) {
  return job.state === 'queued' || job.state === 'running'
}

const jobKey = (world: string, id: string | null) => ['buildJob', world, id] as const
const secondaryAction = 'inline-flex min-h-11 items-center rounded text-sm font-medium text-gray-200 underline decoration-gray-500 underline-offset-4 hover:text-neon-cyan focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan'

export default function WorldBuildPanel({ world, branch, readOnly }: WorldBuildPanelProps) {
  const { t, i18n } = useTranslation('worlds')
  const queryClient = useQueryClient()
  const storageKey = `dreamulator-build:${JSON.stringify([world, branch])}`
  const [jobId, setJobId] = useState(() => {
    try {
      return window.localStorage.getItem(storageKey)
    } catch {
      return null
    }
  })

  const grid = useQuery({
    queryKey: worldParametersKey(world, branch),
    queryFn: () => api.getWorldParameters(world, branch),
    enabled: !readOnly,
    retry: false,
  })

  const start = useMutation({
    mutationFn: () => api.startBuildJob(world, { branch }),
    onSuccess: (job) => {
      queryClient.setQueryData(jobKey(world, job.id), job)
      setJobId(job.id)
      try {
        window.localStorage.setItem(storageKey, job.id)
      } catch {
        return
      }
    },
  })

  const validation = useMutation({ mutationFn: () => api.validateWorld(world) })
  const snapshotUrl = api.getWorldSnapshotUrl(world)
  const status = useQuery({
    queryKey: jobKey(world, jobId),
    queryFn: () => api.getBuildJob(world, jobId!),
    enabled: !!jobId && !readOnly,
    refetchInterval: ({ state: { data, error } }) => {
      if (error instanceof ApiError && error.status === 404) return false
      return error || !data || isActive(data) ? 1000 : false
    },
    retry: false,
    refetchOnWindowFocus: false,
  })
  const job = status.data
  const jobTimestamp = job?.finished_at ?? job?.updated_at
  const lost = status.error instanceof ApiError && status.error.status === 404
  const terminal = !!job && !isActive(job) && !status.error
  const showResults = terminal || lost
  const guideMap = useWorkflowTutorial(state => state.progress?.step === 'map' && state.progress.world === world && !branch)

  useEffect(() => {
    if (job?.state === 'succeeded' && !status.error) tutorialMilestone({ type: 'built', world, branch })
  }, [job?.state, world, branch, status.error])

  useEffect(() => {
    if (!showResults) return
    void queryClient.invalidateQueries({
      predicate: ({ queryKey }) => queryKey[0] !== 'buildJob' && queryKey[1] === world,
    })
  }, [showResults, jobId, world, queryClient])

  const maps = useQuery({
    queryKey: ['mapPlanets', world, branch],
    queryFn: () => api.listMapPlanets(world, branch),
    enabled: showResults && !readOnly,
  })
  const active = !!jobId && !terminal && !lost
  const snapshotWaiting = active || start.isPending
  const errors = [...new Set([
    ...(job?.error ? [job.error] : []),
    ...(job?.result?.errors ?? []).filter((error) =>
      !job?.stages.some((stage) => stage.errors.includes(error))),
  ])]
  const firstStageError = job?.state === 'failed'
    ? job.stages.find((stage) => stage.errors.length > 0)?.errors[0] : undefined
  const conflict = start.error instanceof ApiError && start.error.status === 409 &&
    start.error.message.endsWith('is already active')
  const worldPath = `/worlds/${encodeURIComponent(world)}`
  const resultParams = new URLSearchParams(branch ? { branch } : {})
  const gridSize = grid.data?.num_cells?.toLocaleString(i18n.resolvedLanguage)
  const builtCells = grid.data?.built_cells
  const needsRebuild = grid.data?.planet?.needs_rebuild ||
    (grid.data && !grid.data.reuses_mesh && builtCells != null && builtCells !== grid.data.num_cells)
  const gridLabel = grid.isPending ? t('build.gridLoading') : gridSize != null
    ? t(grid.data?.reuses_mesh ? 'build.gridReused' : 'build.gridConfigured', { cells: gridSize })
    : t(grid.data?.reuses_mesh ? 'build.gridReusedUnknown' : 'build.gridUnknown')

  return (
    <section id="build" data-tutorial-anchor={snapshotWaiting ? 'building' : undefined}
      className="glass-panel mb-4 space-y-3 p-4" aria-labelledby="build-title">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="build-title" className="font-semibold text-neon-cyan">{t('build.title')}</h2>
          <p className="text-sm text-gray-400">{t('build.target', { branch: branch ?? t('label.baseWorld') })}</p>
          {!readOnly && <p className="text-sm text-gray-400" role="status">{gridLabel}</p>}
          {needsRebuild && <p role="status" className="text-sm text-amber-200">
            {t('parameters.rebuild')}
          </p>}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {snapshotUrl && (
            <a
              href={snapshotWaiting ? undefined : snapshotUrl}
              role={snapshotWaiting ? 'link' : undefined}
              aria-disabled={snapshotWaiting || undefined}
              data-tutorial-anchor={snapshotWaiting ? undefined : 'snapshot'}
              onClick={() => { if (!snapshotWaiting) tutorialMilestone({ type: 'backup', world }) }}
              title={t(snapshotWaiting ? 'build.snapshotAfterBuild' : 'build.snapshotScope')}
              target="_blank"
              rel="noopener"
              className={snapshotWaiting ? 'inline-flex min-h-11 cursor-not-allowed items-center text-sm font-medium text-gray-400' : secondaryAction}
            >
              {t('build.downloadSnapshot')}
            </a>
          )}
          <button
            type="button"
            className={`${secondaryAction} disabled:text-gray-400 disabled:no-underline`}
            title={t('build.validateSettingsHelp')}
            onClick={() => validation.mutate()}
            disabled={validation.isPending}
          >
            {t(validation.isPending ? 'build.validating' : 'build.validateSettings')}
          </button>
          {!readOnly && (
            <button
              type="button"
              data-tutorial-anchor="build"
              onClick={() => start.mutate()}
              disabled={start.isPending || active || grid.isPending}
              className="px-4 py-2 rounded-lg font-medium bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 disabled:opacity-50"
            >
              {start.isPending ? t('build.starting') :
                lost ? t('build.startNew') :
                  job?.state === 'failed' || start.isError ? t('build.retry') : t('action.buildWorld')}
            </button>
          )}
        </div>
      </div>

      {validation.isError ? (
        <p role="alert" className="break-words text-sm text-red-300">
          {t('build.validationError', { error: validation.error.message })}
        </p>
      ) : validation.data && !validation.isPending && (
        <div role="status" className={`text-sm ${validation.data.ok ? 'text-green-300' : 'text-red-300'}`}>
          <p>{t(validation.data.ok ? 'build.validationPassed' : 'build.validationFailed')}</p>
          {validation.data.errors.length > 0 && (
            <ul className="list-disc break-words pl-5">
              {validation.data.errors.map((error, index) => <li key={index}>{error}</li>)}
            </ul>
          )}
        </div>
      )}

      {readOnly ? <p className="text-sm text-gray-400">{t('build.referenceRoot')}</p> : (
        <>
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
            <div className="space-y-1" role="status">
              {start.error && <p className="text-amber-300">{conflict ? t('build.busy') : t('build.startError', { error: start.error.message })}</p>}
              {lost ? <p className="text-amber-300">{t('build.statusLost')}</p> : status.error ? (
                <p className="text-amber-300">{t('build.statusError', { error: status.error.message })}</p>
              ) : job ? <p className="font-medium">{t(`build.job.${job.state}`)}</p> :
                jobId && <p className="text-gray-400">{t('build.checking')}</p>}
            </div>
            {job && !lost && jobTimestamp && (
              <>
                <span className="text-gray-400">{t('build.elapsed', { seconds: Math.floor(job.elapsed_seconds) })}</span>
                <span className="text-gray-400">{t(job.finished_at ? 'build.finishedAt' : 'build.stageChanged')} <time dateTime={jobTimestamp}>
                  {new Date(jobTimestamp).toLocaleString(i18n.resolvedLanguage)}
                </time></span>
              </>
            )}
          </div>

          {job && !lost && (
            <>
              {errors.length > 0 && (
                <ul className="list-disc pl-5 break-words text-sm text-red-300">
                  {errors.map((error) => <li key={error}>{error}</li>)}
                </ul>
              )}
              {!errors.length && firstStageError && <p className="break-words text-sm text-red-300">{firstStageError}</p>}
              {job.state === 'failed' && <p className="text-sm text-gray-400">{t('build.failedHint')}</p>}
              {job.stages.length > 0 && (
                <details key={job.id} open={isActive(job)} className="text-sm">
                  <summary className="w-fit cursor-pointer rounded text-gray-300 hover:text-neon-cyan focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan">
                    {t('build.stageDetails')}
                  </summary>
                  <ol className="mt-2 divide-y divide-space-border rounded border border-space-border">
                    {job.stages.map((stage) => (
                      <li key={`${stage.engine}:${stage.bootstrap}`} className="px-3 py-2">
                        <div className="flex items-baseline justify-between gap-3">
                          <span>
                            {t(`layer.${stage.layer}`, { defaultValue: stage.engine })}
                            {stage.bootstrap && <span className="ml-2 text-xs text-gray-400">{t('build.bootstrap')}</span>}
                          </span>
                          <span className={stage.state === 'failed' ? 'text-red-300' :
                            stage.state === 'succeeded' ? 'text-green-300' :
                              stage.state === 'running' || stage.state === 'validating' ? 'text-neon-cyan' : 'text-gray-400'}>
                            {t(`build.stage.${stage.state}`)}
                          </span>
                        </div>
                        {stage.errors.length > 0 && (
                          <ul className="mt-1 list-disc pl-5 break-words text-red-300">
                            {stage.errors.map((error, index) => <li key={index}>{error}</li>)}
                          </ul>
                        )}
                      </li>
                    ))}
                  </ol>
                </details>
              )}
            </>
          )}

          {showResults && !!maps.data?.length && (
            <ul className="space-y-1 text-sm">
              {maps.data.map((planet) => {
                const mapPath = `${worldPath}/map/${encodeURIComponent(planet)}`
                const suffix = branch ? `?${resultParams}` : guideMap ? '?layer=temperature' : ''
                return (
                  <li key={planet} className="flex flex-wrap gap-3">
                    <span className="text-gray-400">{planet}</span>
                    <Link data-tutorial-anchor="map" className="text-neon-cyan hover:underline" to={`${mapPath}${suffix}`}>{t('build.openMap')}</Link>
                  </li>
                )
              })}
            </ul>
          )}
        </>
      )}
    </section>
  )
}
