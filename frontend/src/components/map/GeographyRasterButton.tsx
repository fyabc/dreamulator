/**
 * GeographyRasterButton — upload a dense land-bias grayscale (Gleba-style
 * probability map) stored as geography_raster.png; takes effect on the next
 * terrain generation alongside geography.yaml.
 */

import { useRef, useState } from 'react'
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
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const staticMode = isStaticMode()

  const handleFile = async (file: File) => {
    const ok = window.confirm(
      `上传锚定灰度图（白=陆、黑=海、中灰=中立）：\n${file.name}\n\n将于下次地形生成时与 geography.yaml 叠加。继续？`
    )
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
        title={staticMode ? '静态模式不可写' : '上传锚定灰度图（Gleba 式概率图，下次生成生效）'}
        className="px-3 py-1 text-sm rounded-lg bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors disabled:opacity-40"
      >
        {busy ? '上传中…' : '⬆ 锚定灰度图'}
      </button>
    </>
  )
}
