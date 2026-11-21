import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { BuildJob } from '../../api/buildJobs'

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
    queryKey: ['buildGrid', world, branch],
    queryFn: () => api.getBuildGrid(world, branch),
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
  const lost = status.error instanceof ApiError && status.error.status === 404
  const terminal = !!job && !isActive(job) && !status.error
  const showResults = terminal || lost

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
  const climateReady = terminal && job.stages.some(({ engine, state }) =>
    engine === 'climate' && (state === 'succeeded' || state === 'skipped'),
  )
  const active = !!jobId && !terminal && !lost
  const snapshotWaiting = active || start.isPending
  const errors = [...new Set([
    ...(job?.error ? [job.error] : []),
    ...(job?.result?.errors ?? []).filter((error) =>
      !job?.stages.some((stage) => stage.errors.includes(error))),
  ])]
  const conflict = start.error instanceof ApiError && start.error.status === 409 &&
    start.error.message.endsWith('is already active')
  const worldPath = `/worlds/${encodeURIComponent(world)}`
  const resultParams = new URLSearchParams(branch ? { branch } : {})
  const gridSize = grid.data?.num_cells?.toLocaleString(i18n.resolvedLanguage)
  const gridLabel = grid.isPending ? t('build.gridLoading') : gridSize != null
    ? t(grid.data?.reuses_mesh ? 'build.gridReused' : 'build.gridConfigured', { cells: gridSize })
    : t(grid.data?.reuses_mesh ? 'build.gridReusedUnknown' : 'build.gridUnknown')

  return (
    <section id="build" className="glass-panel mb-4 space-y-3 p-4" aria-labelledby="build-title">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="build-title" className="font-semibold text-neon-cyan">{t('build.title')}</h2>
          <p className="text-sm text-gray-400">{t('build.target', { branch: branch ?? t('label.baseWorld') })}</p>
          {!readOnly && <p className="text-sm text-gray-400" role="status">{gridLabel}</p>}
        </div>
        {!readOnly && (
          <button
            type="button"
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

      {readOnly ? <p className="text-sm text-gray-400">{t('build.referenceRoot')}</p> : (
        <>
          <div className="space-y-1 text-sm" role="status">
            {start.error && <p className="text-amber-300">{conflict ? t('build.busy') : t('build.startError', { error: start.error.message })}</p>}
            {lost ? <p className="text-amber-300">{t('build.statusLost')}</p> : status.error ? (
              <p className="text-amber-300">{t('build.statusError', { error: status.error.message })}</p>
            ) : job ? <p className="font-medium">{t(`build.job.${job.state}`)}</p> :
              jobId && <p className="text-gray-400">{t('build.checking')}</p>}
          </div>

          {job && !lost && (
            <>
              <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-400">
                <span>{t('build.elapsed', { seconds: Math.floor(job.elapsed_seconds) })}</span>
                <span>{t('build.stageChanged')} <time dateTime={job.updated_at}>
                  {new Date(job.updated_at).toLocaleString(i18n.resolvedLanguage)}
                </time></span>
              </p>
              {job.stages.length > 0 && (
                <ol className="divide-y divide-space-border rounded border border-space-border text-sm">
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
              )}
              {errors.length > 0 && (
                <ul className="list-disc pl-5 break-words text-sm text-red-300">
                  {errors.map((error) => <li key={error}>{error}</li>)}
                </ul>
              )}
              {job.state === 'failed' && <p className="text-sm text-gray-400">{t('build.failedHint')}</p>}
            </>
          )}

          {showResults && !!maps.data?.length && (
            <ul className="space-y-1 text-sm">
              {maps.data.map((planet) => {
                const mapPath = `${worldPath}/map/${encodeURIComponent(planet)}`
                const suffix = branch ? `?${resultParams}` : ''
                const climateParams = new URLSearchParams(resultParams)
                climateParams.set('layer', 'temperature')
                return (
                  <li key={planet} className="flex flex-wrap gap-3">
                    <span className="text-gray-400">{planet}</span>
                    <Link className="text-neon-cyan hover:underline" to={`${mapPath}${suffix}`}>{t('build.openMap')}</Link>
                    {climateReady && <Link className="text-neon-cyan hover:underline" to={`${mapPath}?${climateParams}`}>{t('build.openTemperature')}</Link>}
                  </li>
                )
              })}
            </ul>
          )}
        </>
      )}
      <div className="border-t border-space-border pt-1">
        <div className="flex flex-wrap items-center gap-x-5">
          <button
            type="button"
            className={`${secondaryAction} disabled:text-gray-400 disabled:no-underline`}
            onClick={() => validation.mutate()}
            disabled={validation.isPending}
          >
            {t(validation.isPending ? 'build.validating' : 'build.validateSettings')}
          </button>
          {snapshotUrl && (snapshotWaiting ? (
            <span className="text-sm text-gray-400" role="status">{t('build.snapshotAfterBuild')}</span>
          ) : (
            <>
              <a href={snapshotUrl} target="_blank" rel="noopener" className={secondaryAction}
                aria-describedby="world-snapshot-scope">{t('build.downloadSnapshot')}</a>
              <p id="world-snapshot-scope" className="pb-2 text-sm text-gray-400 sm:pb-0">{t('build.snapshotScope')}</p>
            </>
          ))}
        </div>
        {validation.isError ? (
          <p role="alert" className="break-words pb-2 text-sm text-red-300">
            {t('build.validationError', { error: validation.error.message })}
          </p>
        ) : validation.data && !validation.isPending && (
          <div role="status" className={`pb-2 text-sm ${validation.data.ok ? 'text-green-300' : 'text-red-300'}`}>
            <p>{t(validation.data.ok ? 'build.validationPassed' : 'build.validationFailed')}</p>
            {validation.data.errors.length > 0 && (
              <ul className="list-disc break-words pl-5">
                {validation.data.errors.map((error, index) => <li key={index}>{error}</li>)}
              </ul>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
