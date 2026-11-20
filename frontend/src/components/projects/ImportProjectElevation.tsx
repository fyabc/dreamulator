import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { makeElevationSource, maxSourceBytes, maxSourceSide, type LocalProject } from '../../projects/elevationProject'
import { projectsKey, updateProject } from '../../projects/projectStore'
import { readRegionWindow, regionPackWindow } from '../../viewers/map/regionWindow'
import type { ElevationRaster } from '../../viewers/packs/elevationRaster'
import type { ElevationWorkerRequest, ElevationWorkerResult } from '../../workers/regionElevation.worker'
import { projectButton, projectField } from './SaveProjectResult'

const defaults = { min: '-1000', max: '3000', sea: '0', span: '46', lat: '0', lon: '0', radius: '6371' }

function decodeSource(blob: Blob, min: number, max: number) {
  return new Promise<ElevationRaster>((resolve, reject) => {
    const worker = new Worker(new URL('../../workers/regionElevation.worker.ts', import.meta.url), { type: 'module' })
    const fail = () => { worker.terminate(); reject(new Error('Invalid elevation PNG')) }
    worker.onerror = fail
    worker.onmessage = ({ data }: MessageEvent<ElevationWorkerResult>) => {
      worker.terminate()
      if (data.kind === 'preview') resolve(data.raster)
      else fail()
    }
    worker.postMessage({ kind: 'project-png', blob, min, max, maxSide: maxSourceSide } satisfies ElevationWorkerRequest)
  })
}

export default function ImportProjectElevation({ world, onSaved }: { world: LocalProject; onSaved: (layerId: string) => void }) {
  const { t } = useTranslation('worlds', { keyPrefix: 'worldData' })
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [values, setValues] = useState(defaults)
  const [error, setError] = useState<'invalidSource' | 'invalidMapping' | null>(null)
  const insert = useMutation({ mutationFn: async (source: File) => {
    const radius = Number(values.radius)
    const selection = readRegionWindow(`${values.lat},${values.lon},${values.span}`, radius)
    const min = Number(values.min)
    const max = Number(values.max)
    const sea = Number(values.sea)
    if (!selection || ['min', 'max', 'sea'].some((key) => !values[key as keyof typeof values].trim()) ||
      [min, max, sea].some((value) => !Number.isFinite(value) || Math.abs(value) > 1e9) || max <= min) {
      setError('invalidMapping')
      return null
    }
    if (source.size === 0 || source.size > maxSourceBytes) { setError('invalidSource'); return null }
    const raster = await decodeSource(source, min, max).catch(() => null)
    if (!raster) { setError('invalidSource'); return null }
    const layer = makeElevationSource(source.name, raster, { window: regionPackWindow(selection, radius),
      min, max, sea, sourceStepKm: selection.spanKm / raster.width }, source)
    await updateProject(world.id, (current) => ({ ...current, layers: [...current.layers, layer] }),
      world.published ? { ...world, layers: [] } : undefined)
    return layer.id
  }, onSuccess: async (id) => {
    if (!id) return
    await queryClient.invalidateQueries({ queryKey: projectsKey })
    setFile(null)
    onSaved(id)
  } })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!file || insert.isPending) return
    setError(null)
    insert.mutate(file)
  }

  return <details className="rounded border border-space-border p-3">
    <summary className="cursor-pointer font-medium text-neon-cyan">{t('importElevation')}</summary>
    <form onSubmit={submit} className="mt-2 space-y-2 text-sm">
      <p>{t('sourceHelp')}</p>
      <label className="flex flex-col gap-1">{t('sourceFile')}
        <input className="max-w-full" key={file === null ? 'empty' : 'selected'} type="file" accept=".png,image/png" disabled={insert.isPending}
          onChange={(event) => { setFile(event.currentTarget.files?.[0] ?? null); setError(null); insert.reset() }} />
        {file && <span className="break-all">{file.name}</span>}
      </label>
      <div className="grid grid-cols-2 gap-2">
        {(Object.keys(defaults) as (keyof typeof defaults)[]).map((key) => <label key={key} className="flex flex-col gap-1">
          {t(`mapping.${key}`)} <input className={projectField} type="number" step="any" required disabled={insert.isPending} value={values[key]}
            onChange={(event) => setValues({ ...values, [key]: event.currentTarget.value })} />
        </label>)}
      </div>
      <button className={projectButton} disabled={!file || insert.isPending}>{t(insert.isPending ? 'saving' : 'saveInput')}</button>
      {(error || insert.isError) && <p role="alert" className="text-red-300">{t(error ?? 'saveFailed')}</p>}
    </form>
  </details>
}
