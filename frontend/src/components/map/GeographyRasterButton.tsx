/**
 * GeographyRasterButton — upload a dense land-bias grayscale (Gleba-style
 * probability map) stored as geography_raster.png; takes effect on the next
 * terrain generation alongside geography.yaml.
 */

import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import { isStaticMode } from '../../api/mode'

export interface GeographyRasterResult {
  ok: boolean
  source_format?: string
  source_resolution?: number[]
  saved?: string
  detail?: string
}

interface Props {
  worldName: string
  branch: string | null
  onUploaded: (result: GeographyRasterResult) => void
}

export default function GeographyRasterButton({ worldName, branch, onUploaded }: Props) {
  const { t } = useTranslation('map')
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const staticMode = isStaticMode()

  const handleFile = async (file: File) => {
    const ok = window.confirm(t('confirm.uploadRaster', { name: file.name }))
    if (!ok) return
    setBusy(true)
    try {
      const result = (await api.uploadGeographyRaster(worldName, file, branch)) as GeographyRasterResult
      onUploaded(result)
    } catch (e) {
      onUploaded({ ok: false, detail: String(e) })
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
        title={staticMode ? t('hint.staticReadonly') : t('hint.uploadRasterTitle')}
        className="px-3 py-1 text-sm rounded-lg bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors disabled:opacity-40"
      >
        {busy ? t('action.uploading') : t('action.uploadRaster')}
      </button>
    </>
  )
}
