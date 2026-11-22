import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '../../api/client'
import type { BuildJob } from '../../api/buildJobs'
import { worldParametersKey } from '../../api/worldParameters'
import { tutorialMilestone } from '../../tutorial/tutorialProgress'
import WorldBuildCard, { buildPrimaryAction, buildSecondaryAction, WorldBuildGridStatus } from './WorldBuildCard'
import WorldBuildProgress from './WorldBuildProgress'

interface WorldBuildPanelProps {
  world: string
  branch: string | null
  readOnly: boolean
  visible: boolean
  hasMap: boolean
}

function isActive(job: BuildJob) {
  return job.state === 'queued' || job.state === 'running'
}

const jobKey = (world: string, id: string | null) => ['buildJob', world, id] as const

export default function WorldBuildPanel({ world, branch, readOnly, visible, hasMap }: WorldBuildPanelProps) {
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
    enabled: visible && !readOnly,
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

  const snapshotUrl = api.getWorldSnapshotUrl(world)
  const status = useQuery({
    queryKey: jobKey(world, jobId),
    queryFn: async () => {
      try {
        return await api.getBuildJob(world, jobId!)
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404)) throw error
        try {
          if (window.localStorage.getItem(storageKey) === jobId) window.localStorage.removeItem(storageKey)
        } catch {
          return null
        }
        return null
      }
    },
    enabled: !!jobId && !readOnly,
    refetchInterval: ({ state: { data, error } }) => {
      return error || data === undefined || (data && isActive(data)) ? 1000 : false
    },
    retry: false,
    refetchOnWindowFocus: false,
  })
  const job = status.data
  const jobTimestamp = job?.finished_at ?? job?.updated_at
  const lost = job === null && !status.error
  const terminal = !!job && !isActive(job) && !status.error
  const showResults = terminal || lost

  useEffect(() => {
    if (job?.state === 'succeeded' && !status.error) tutorialMilestone({ type: 'built', world, branch })
  }, [job?.state, world, branch, status.error])

  useEffect(() => {
    if (!showResults) return
    void queryClient.invalidateQueries({
      predicate: ({ queryKey }) => queryKey[0] !== 'buildJob' && queryKey[1] === world,
    })
  }, [showResults, jobId, world, queryClient])

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
  return (
    <WorldBuildCard branch={branch} visible={visible} buildingAnchor={snapshotWaiting}
      summary={!readOnly && <WorldBuildGridStatus grid={grid.data} loading={grid.isPending} />}
      savedMap={hasMap ? { cells: grid.data?.built_cells ?? undefined } : undefined}
      checkSettings={() => api.validateWorld(world)}
      backup={snapshotUrl && (
        <a
          href={snapshotWaiting ? undefined : snapshotUrl}
          role={snapshotWaiting ? 'link' : undefined}
          aria-disabled={snapshotWaiting || undefined}
          data-tutorial-anchor={snapshotWaiting ? undefined : 'snapshot'}
          onClick={() => { if (!snapshotWaiting) tutorialMilestone({ type: 'backup', world }) }}
          title={t(snapshotWaiting ? 'build.snapshotAfterBuild' : 'build.snapshotScope')}
          target="_blank"
          rel="noopener"
          className={snapshotWaiting ? 'inline-flex min-h-11 cursor-not-allowed items-center text-sm font-medium text-gray-400' : buildSecondaryAction}
        >
          {t('build.downloadSnapshot')}
        </a>
      )}
      actions={!readOnly && (
        <button
          type="button"
          data-tutorial-anchor="build"
          onClick={() => start.mutate()}
          disabled={start.isPending || active || grid.isPending}
          className={buildPrimaryAction}
          title={t('build.fullScope')}
        >
          {start.isPending ? t('build.starting') : job?.state === 'failed' || start.isError ? t('build.retry') : t('action.buildWorld')}
        </button>
      )}>
      {readOnly ? <p className="text-sm text-gray-400">{t('build.referenceRoot')}</p> : (
        <>
          {(start.error || active || job) && <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
            <div className="space-y-1" role="status">
              {start.error && <p className="text-amber-300">{conflict ? t('build.busy') : t('build.startError', { error: start.error.message })}</p>}
              {status.error ? (
                <p className="text-amber-300">{t('build.statusError', { error: status.error.message })}</p>
              ) : job ? <p className="font-medium">{t(`build.job.${job.state}`)}</p> :
                jobId && <p className="text-gray-400">{t('build.checking')}</p>}
            </div>
            {job && jobTimestamp && (
              <>
                <span className="text-gray-400">{t('build.elapsed', { seconds: Math.floor(job.elapsed_seconds) })}</span>
                <span className="text-gray-400">{t(job.finished_at ? 'build.finishedAt' : 'build.stageChanged')} <time dateTime={jobTimestamp}>
                  {new Date(jobTimestamp).toLocaleString(i18n.resolvedLanguage)}
                </time></span>
              </>
            )}
          </div>}

          {job && (
            <>
              {errors.length > 0 && (
                <ul className="list-disc pl-5 break-words text-sm text-red-300">
                  {errors.map((error) => <li key={error}>{error}</li>)}
                </ul>
              )}
              {!errors.length && firstStageError && <p className="break-words text-sm text-red-300">{firstStageError}</p>}
              {job.state === 'failed' && <p className="text-sm text-gray-400">{t('build.failedHint')}</p>}
              {job.stages.length > 0 && <WorldBuildProgress key={job.id} job={job} running={isActive(job)} />}
            </>
          )}
        </>
      )}
    </WorldBuildCard>
  )
}
