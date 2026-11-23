import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import type { LabParameter, ParameterLabState } from '../../api/parameterLab'
import { worldParametersKey } from '../../api/worldParameters'

const labKey = (world: string, branch: string | null, planet: string) =>
  ['parameterLab', world, branch, planet] as const

const LAYER_ORDER = ['astronomy', 'geological', 'climate', 'ecology', 'civilization']

function groupParameters(parameters: LabParameter[]) {
  const order: string[] = []
  const groups = new Map<string, LabParameter[]>()
  for (const parameter of parameters) {
    if (!groups.has(parameter.group)) {
      groups.set(parameter.group, [])
      order.push(parameter.group)
    }
    groups.get(parameter.group)!.push(parameter)
  }
  return order.map(group => ({ group, parameters: groups.get(group)! }))
}

function boundsOf(parameter: LabParameter) {
  const range = parameter.range ?? {}
  return {
    min: range.minimum ?? range.exclusiveMinimum,
    max: range.maximum,
    exclusiveMin: range.exclusiveMinimum,
  }
}

export default function ParameterLab({ world, branch, planet, openBuild }: {
  world: string
  branch: string | null
  planet: string
  openBuild?: () => void
}) {
  const { t } = useTranslation('map')
  const queryClient = useQueryClient()
  const location = useLocation()
  const navigate = useNavigate()
  const [draft, setDraft] = useState<Record<string, number>>({})
  const [branchName, setBranchName] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [savedState, setSavedState] = useState<ParameterLabState | null>(null)

  const query = useQuery({
    queryKey: labKey(world, branch, planet),
    queryFn: () => api.getParameterLab(world, planet, branch),
    enabled: Boolean(world && planet),
    retry: false,
  })
  const state: ParameterLabState | undefined = query.data
  const groups = useMemo(() => groupParameters(state?.parameters ?? []), [state])

  const changedValues = useMemo(() => Object.fromEntries(
    (state?.parameters ?? [])
      .filter(parameter => draft[parameter.id] !== undefined && draft[parameter.id] !== parameter.value)
      .map(parameter => [parameter.id, draft[parameter.id]]),
  ), [state, draft])
  const changed = Object.keys(changedValues).length > 0
  const valid = changed && (state?.parameters ?? []).every(parameter => {
    if (draft[parameter.id] === undefined || !parameter.editable) return true
    const value = draft[parameter.id]
    if (!Number.isFinite(value)) return false
    const { min, max, exclusiveMin } = boundsOf(parameter)
    if (min !== undefined && (exclusiveMin !== undefined ? value <= min : value < min)) return false
    return max === undefined || value <= max
  })

  const invalidateAfterSave = (next: ParameterLabState) => {
    setDraft({})
    setSavedState(next)
    setMessage(t('parameterLab.saved'))
    queryClient.setQueryData(labKey(world, next.branch, next.planet ?? planet), next)
    void queryClient.invalidateQueries({ queryKey: ['buildPlan', world, next.branch] })
    void queryClient.invalidateQueries({ queryKey: ['buildPlan', world, branch] })
    void queryClient.invalidateQueries({ queryKey: ['world', world] })
    void queryClient.invalidateQueries({ queryKey: ['branches', world] })
    void queryClient.invalidateQueries({ queryKey: worldParametersKey(world, next.branch) })
  }

  const save = useMutation({
    mutationFn: () => api.saveParameterLab(world, planet, branch, state!.revision, changedValues),
    onSuccess: invalidateAfterSave,
  })
  const fork = useMutation({
    mutationFn: () => api.saveParameterLabBranch(world, planet, branch, branchName.trim(), changedValues),
    onSuccess: (next) => {
      invalidateAfterSave(next)
      setBranchName('')
      if (!next.branch) return
      const params = new URLSearchParams(location.search)
      params.set('branch', next.branch)
      params.set('trial', 'climate')
      navigate(`${location.pathname}?${params}`)
    },
  })

  const error = save.error ?? fork.error
  const errorMessage = error instanceof ApiError
    ? (error.status === 409 ? t('parameterLab.conflict') : t('parameterLab.error', { message: error.message }))
    : error instanceof Error ? t('parameterLab.error', { message: error.message }) : null
  const conflict = error instanceof ApiError && error.status === 409
  const busy = query.isPending || save.isPending || fork.isPending
  const affected = useMemo(() => {
    const changedParameters = (state?.parameters ?? []).filter(parameter =>
      draft[parameter.id] !== undefined && draft[parameter.id] !== parameter.value)
    const layers = new Set(changedParameters.flatMap(parameter => parameter.consumers))
    return [...layers].sort((a, b) => LAYER_ORDER.indexOf(a) - LAYER_ORDER.indexOf(b))
  }, [state, draft])

  const change = (parameter: LabParameter, raw: string) => {
    setMessage(null)
    setSavedState(null)
    const value = raw === '' ? Number.NaN : Number(raw)
    setDraft(previous => ({ ...previous, [parameter.id]: value }))
  }

  return (
    <div className="space-y-3 text-xs">
      <p className="leading-relaxed text-gray-300">{t('parameterLab.description')}</p>
      {query.isPending && <p role="status" className="text-gray-300">{t('parameterLab.reading')}</p>}
      {query.isError && <p role="alert" className="text-red-200">{t('parameterLab.unavailable')}</p>}
      {state?.read_only && <p className="text-amber-200">{t('parameterLab.readOnly')}</p>}
      {state && <form className="space-y-3" onSubmit={event => {
        event.preventDefault()
        if (valid && !busy) save.mutate()
      }}>
        {groups.map(({ group, parameters }) => <fieldset key={group} className="space-y-2" disabled={busy}>
          <legend className="mb-1 text-xs font-semibold text-gray-200">{t(`worlds:layer.${group}`)}</legend>
          {parameters.map(parameter => {
            const key = parameter.id.split('.').pop() ?? parameter.id
            const value = draft[parameter.id] ?? parameter.value
            const blocked = !parameter.editable
            return <label key={parameter.id} className="flex items-center justify-between gap-2 text-gray-300"
              title={t(`parameterLab.params.${key}.help`)}>
              <span className="min-w-0">
                {t(`parameterLab.params.${key}.label`)}
                {blocked && <span className="ml-1 text-[10px] text-amber-200">
                  {parameter.reason === 'fork' ? t('parameterLab.forkBlocked') : t('parameterLab.missing')}
                </span>}
              </span>
              <span className="flex shrink-0 items-center gap-1">
                <input type="number" step="any" disabled={blocked}
                  value={value === null || Number.isNaN(value) ? '' : value}
                  onChange={event => change(parameter, event.target.value)}
                  className="w-24 rounded border border-space-border bg-space-surface px-2 py-1.5 text-right text-sm tabular-nums text-gray-200 focus-visible:outline focus-visible:outline-neon-cyan disabled:opacity-50" />
                {parameter.unit && <span className="w-6 text-[10px] text-gray-500">
                  {parameter.unit === 'deg' ? '°' : parameter.unit === 'day' ? t('parameterLab.dayUnit', { defaultValue: 'd' }) : parameter.unit}
                </span>}
              </span>
            </label>
          })}
        </fieldset>)}
        {!valid && changed && <p className="text-amber-200">{t('parameterLab.invalid')}</p>}
        {affected.length > 0 && <p className="text-gray-400">
          {t('parameterLab.impact', { layers: affected.map(layer => t(`worlds:layer.${layer}`)).join(t('buildPlan.listSeparator')) })}
        </p>}
        <div className="flex flex-wrap items-center gap-2">
          <button type="submit" disabled={!valid || busy}
            className="atlas-tool-button min-h-9 text-xs">
            {save.isPending ? t('parameterLab.saving') : t('parameterLab.save')}
          </button>
          {message && <span role="status" className="text-green-300">{message}</span>}
          {conflict && <button type="button" onClick={() => { setDraft({}); setMessage(null); void query.refetch() }}
            className="atlas-tool-button min-h-9 text-xs">{t('parameterLab.reload')}</button>}
        </div>
        {errorMessage && <p role="alert" className="text-red-200">{errorMessage}</p>}
        {savedState?.start_layer && message && <div className="flex items-center gap-2">
          <span className="text-gray-400">{t('parameterLab.startLayer', { layer: t(`worlds:layer.${savedState.start_layer}`) })}</span>
          <button type="button" onClick={() => {
            openBuild?.()
            window.dispatchEvent(new CustomEvent('dreamulator:open-build-plan'))
          }} className="text-neon-cyan underline underline-offset-4">{t('parameterLab.goBuild')}</button>
        </div>}
        {!state.read_only && <div className="space-y-1 border-t border-space-border pt-2">
          <label className="block text-gray-200">
            {t('parameterLab.branchName')}
            <input value={branchName} onChange={event => setBranchName(event.target.value)}
              maxLength={64} autoComplete="off" placeholder="climate-variant"
              className="mt-1 min-h-9 w-full rounded border border-space-border bg-space-bg px-2 text-gray-100" />
          </label>
          <p className="text-gray-500">{t('parameterLab.branchHint')}</p>
          <button type="button" disabled={!valid || busy || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(branchName.trim())}
            onClick={() => fork.mutate()} className="atlas-tool-button min-h-9 text-xs">
            {fork.isPending ? t('parameterLab.saving') : t('parameterLab.saveAsBranch')}
          </button>
        </div>}
      </form>}
    </div>
  )
}
