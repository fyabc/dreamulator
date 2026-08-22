/**
 * ImportElevationButton — upload an external heightmap (PNG/TIFF) to the
 * import-elevation endpoint.  First write-UI on the (otherwise read-only)
 * map viewer; hidden-disabled in static mode.
 */

import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'

export interface ImportElevationResult {
  ok: boolean
  source_format?: string
  source_resolution?: number[]
  output_resolution?: number[]
  was_resampled?: boolean
  range?: number[]
  stale_layers?: string[]
  detail?: string
}

interface Props {
  worldName: string
  planetId: string
  branch: string | null
  onImported: (result: ImportElevationResult) => void
}

export default function ImportElevationButton({ worldName, planetId, branch, onImported }: Props) {
  const { t } = useTranslation('map')
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const staticMode = isStaticMode()

  const handleFile = async (file: File) => {
    const ok = window.confirm(t('confirm.importHeightmap', { name: file.name }))
    if (!ok) return
    setBusy(true)
    try {
      const result = (await api.importElevation(worldName, planetId, file, branch)) as ImportElevationResult
      onImported(result)
    } catch (e) {
      onImported({ ok: false, detail: String(e) })
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".png,.tif,.tiff"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) void handleFile(f)
        }}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={busy || staticMode}
        title={staticMode ? t('hint.staticReadonly') : t('hint.importHeightmapTitle')}
        className="px-3 py-1 text-sm rounded-lg bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors disabled:opacity-40"
      >
        {busy ? t('action.importing') : t('action.importHeightmap')}
      </button>
    </>
  )
}
