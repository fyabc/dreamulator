import { useEffect, useRef, useState } from 'react'
import type { ElevationWorkerRequest, ElevationWorkerResult } from '../../workers/regionElevation.worker'
import type { ElevationFormat, ElevationRaster } from './elevationRaster'
import { downloadBlob } from '../../utils/downloadBlob'

export type ElevationInput = Exclude<ElevationWorkerRequest, { kind: 'export' }>
type Ready = Extract<ElevationWorkerResult, { kind: 'preview' | 'ready' }>

export function useRegionElevation(input: ElevationInput | null) {
  const workerRef = useRef<Worker | null>(null)
  const filename = useRef<string | null>(null)
  const [ready, setReady] = useState<Ready | null>(null)
  const [context, setContext] = useState<ElevationRaster | null>(null)
  const [failed, setFailed] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    setReady(null)
    setContext(null)
    setFailed(false)
    setExporting(false)
    if (!input) return
    const fail = () => { setFailed(true); setExporting(false) }
    try {
      const worker = new Worker(new URL('../../workers/regionElevation.worker.ts', import.meta.url), { type: 'module' })
      workerRef.current = worker
      worker.onerror = fail
      worker.onmessage = ({ data }: MessageEvent<ElevationWorkerResult>) => {
        if (data.kind === 'error') fail()
        else if (data.kind === 'file' && filename.current) {
          downloadBlob(data.blob, filename.current)
          setExporting(false)
        } else if (data.kind === 'preview' || data.kind === 'ready') setReady(data)
        else if (data.kind === 'context') {
          setContext(data.raster)
          if (input.kind === 'context') worker.terminate()
        }
      }
      worker.postMessage(input)
      return () => { worker.terminate(); workerRef.current = null }
    } catch {
      fail()
    }
  }, [input, attempt])

  return {
    ready, context, failed, exporting,
    retry: () => setAttempt((previous) => previous + 1),
    download: (name: string, size: number | null, format: ElevationFormat, metadata: Record<string, unknown>, raster?: ElevationRaster) => {
      if (!workerRef.current || !ready || exporting) return
      filename.current = `${name}.${format}`
      setFailed(false)
      setExporting(true)
      workerRef.current.postMessage({ kind: 'export', size, format, metadata, raster } satisfies ElevationWorkerRequest)
    },
  }
}
