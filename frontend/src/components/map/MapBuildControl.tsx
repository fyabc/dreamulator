import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '../../api/client'
import { isStaticMode } from '../../api/mode'
import type { BuildJob, BuildPlan } from '../../api/buildJobs'
import MapBuildStrip from './MapBuildStrip'
import { planLayerState } from './layerStripState'

interface Props {
  world: string
  branch: string | null
  /** Called after a successful build so the viewer can show the formal result. */
  onBuilt?: () => void
}

const jobKey = (world: string, id: string | null) => ['buildJob', world, id] as const
const planKey = (world: string, branch: string | null) => ['buildPlan', world, branch] as const
const storageKey = (world: string, branch: string | null) =>
  `dreamulator-build:${JSON.stringify([world, branch])}`

function isActive(job: BuildJob | null | undefined) {
  return job?.state === 'queued' || job?.state === 'running'
}

function readStoredJob(world: string, branch: string | null): string | null {
  try {
    return window.localStorage.getItem(storageKey(world, branch))
  } catch {
    return null
  }
}

/**
 * Build plan and in-map build for the world/branch bar.
 *
 * Shows which engine layers are out of date, starts a background build from
 * the earliest one, and refreshes the map when it finishes. Builds are a
 * desktop, API-mode action; the control renders nothing in static mode and on
 * read-only reference roots.
 */
export default function MapBuildControl({ world, branch, onBuilt }: Props) {
  const { t } = useTranslation('map')
  const queryClient = useQueryClient()
  const staticMode = isStaticMode()
  const [open, setOpen] = useState(false)
  const [jobId, setJobId] = useState<string | null>(() => readStoredJob(world, branch))
  const wrapper = useRef<HTMLDivElement>(null)
  /** Only a build started here may switch the viewer to the official result. */
  const startedHere = useRef(false)

  const plan = useQuery({
    queryKey: planKey(world, branch),
    queryFn: () => api.getBuildPlan(world, branch),
    enabled: !staticMode && !!world,
    retry: false,
    staleTime: 10_000,
    refetchOnWindowFocus: true,
  })

  const status = useQuery({
    queryKey: jobKey(world, jobId),
    queryFn: async () => {
      try {
        return await api.getBuildJob(world, jobId!)
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          try {
            window.localStorage.removeItem(storageKey(world, branch))
          } catch {
            return null
          }
          return null
        }
        throw error
      }
    },
    enabled: !staticMode && !!jobId,
    refetchInterval: ({ state: { data, error } }) =>
      error || data === undefined || isActive(data) ? 1000 : false,
    retry: false,
    refetchOnWindowFocus: false,
  })
  const job = status.data
  const active = isActive(job)

  const start = useMutation({
    mutationFn: () => api.startBuildJob(world, {
      branch,
      start_layer: plan.data?.start_layer ?? null,
    }),
    onSuccess: (created) => {
      startedHere.current = true
      queryClient.setQueryData(jobKey(world, created.id), created)
      setJobId(created.id)
      try {
        window.localStorage.setItem(storageKey(world, branch), created.id)
      } catch {
        // The job still runs; only its id is lost across reloads.
      }
      setOpen(true)
    },
  })

  // Close on outside click / Escape while the popover is open.
  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => {
      if (!wrapper.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  // Successful builds: refresh every map query for this world and show the
  // formal result. The plan is refetched through the same invalidation.
  const finished = job?.state === 'succeeded' ? job.finished_at ?? job.updated_at : null
  const handled = useRef<string | null>(null)
  useEffect(() => {
    if (!finished || handled.current === finished) return
    handled.current = finished
    void queryClient.invalidateQueries({
      predicate: ({ queryKey }) => queryKey[0] !== 'buildJob' && queryKey[1] === world,
    })
    if (startedHere.current) onBuilt?.()
  }, [finished, world, queryClient, onBuilt])

  if (staticMode) return null
  if (plan.isError) {
    return <div className="hidden shrink-0 items-center lg:flex">
      <span className="rounded border border-space-border px-2 py-0.5 text-xs text-slate-500"
        title={plan.error instanceof Error ? plan.error.message : undefined}>
        {t('buildPlan.unavailable')}
      </span>
    </div>
  }
  const data: BuildPlan | undefined = plan.data
  if (!data || data.read_only) return null

  const runningLayer = job?.stages.find(stage => stage.state === 'running')?.layer
  const doneStages = job?.stages.filter(stage => stage.state === 'succeeded' || stage.state === 'skipped').length ?? 0
  const totalStages = job?.stages.length ?? 0
  const failure = job?.error || job?.stages.flatMap(stage => stage.errors)[0] ||
    job?.result?.errors[0] || (start.error instanceof Error ? start.error.message : null)
  const label = (name: string) => t(`worlds:layer.${name}`)
  const recompute = new Set(data.recompute)

  return (
    <div ref={wrapper} className="relative hidden shrink-0 items-center lg:flex">
      <MapBuildStrip plan={data} job={job ?? null} active={active} open={open}
        onToggle={() => setOpen(value => !value)} />
      {open && <div className="absolute right-0 top-full z-40 mt-1 w-80 max-w-[calc(100vw-1.5rem)] space-y-2 rounded border border-space-border bg-space-panel p-3 text-xs shadow-xl">
        <p className="font-medium text-gray-200">{t('buildPlan.title')}</p>
        <ul className="space-y-1">
          {data.layers.map(layer => {
            const state = planLayerState(layer, recompute)
            return <li key={layer.name} className="flex items-center justify-between gap-2">
              <span className="text-gray-300">{label(layer.name)}</span>
              <span className={state === 'stale' ? 'text-amber-200'
                : state === 'upstream' ? 'text-amber-200/70'
                  : state === 'fresh' ? 'text-gray-500' : 'text-slate-400'}>
                {t(`buildPlan.state.${state}`)}
                {!layer.input_source && layer.derived_fresh !== 'fresh' && ` · ${t('buildPlan.noInput')}`}
              </span>
            </li>
          })}
        </ul>
        <p className="text-gray-400">
          {data.start_layer
            ? t('buildPlan.recompute', { layers: data.recompute.map(label).join(' → ') })
            : t('buildPlan.fresh')}
        </p>
        {active && <p role="status" className="text-amber-200">
          {t('buildPlan.progress', { done: doneStages, total: totalStages || '…',
            seconds: Math.round(job?.elapsed_seconds ?? 0) })}
          {runningLayer ? ` · ${label(runningLayer)}` : ''}
        </p>}
        {job?.state === 'succeeded' && <p role="status" className="text-green-300">{t('buildPlan.done')}</p>}
        {job?.state === 'failed' && failure && <p role="alert" className="break-words text-red-300">
          {t('buildPlan.failed')}: {failure}
        </p>}
        {!active && start.isError && failure && <p role="alert" className="break-words text-red-300">{failure}</p>}
        <button type="button" onClick={() => start.mutate()}
          disabled={!data.start_layer || active || start.isPending}
          className="inline-flex min-h-8 w-full items-center justify-center rounded border border-neon-cyan/40 bg-neon-cyan/10 px-3 text-sm font-medium text-neon-cyan hover:bg-neon-cyan/20 disabled:cursor-not-allowed disabled:opacity-40">
          {active ? t('buildPlan.building')
            : data.start_layer ? t('buildPlan.startFrom', { layer: label(data.start_layer) })
            : t('buildPlan.fresh')}
        </button>
        <p className="text-gray-500">{t('buildPlan.note')}</p>
      </div>}
    </div>
  )
}
