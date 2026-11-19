import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ElevationFormat } from '../../viewers/packs/elevationRaster'

const SIZES = [64, 128, 256, 512, 1024, 2048]

interface Props {
  original?: { width: number; height: number }
  defaultSize: number | null
  sourceStepKm: number
  extentKm: number
  exporting: boolean
  failed: boolean
  fixedSize?: boolean
  downloadLabel?: string
  onDownload: (size: number | null, format: ElevationFormat) => void
}

export default function RegionElevationDownload({ original, defaultSize, sourceStepKm, extentKm, exporting, failed,
  fixedSize = false, downloadLabel, onDownload }: Props) {
  const { t } = useTranslation('map')
  const [override, setOverride] = useState<string | null>(null)
  const [format, setFormat] = useState<ElevationFormat>('png')
  const selected = override ?? (defaultSize === null ? 'native' : String(defaultSize))
  const size = selected === 'native' ? null : Number(selected)
  const sizes = defaultSize === null ? SIZES : [...new Set([defaultSize, ...SIZES])].sort((left, right) => left - right)
  const dimensions = (length: number) => {
    if (!original) return `${length} × ${length}`
    const longest = Math.max(original.width, original.height)
    return `${Math.max(1, Math.round(length * original.width / longest))} × ${Math.max(1, Math.round(length * original.height / longest))}`
  }
  return (
    <div className="space-y-2">
      {!fixedSize && <label className="block" title={t('packs.export.sizeHint')}>
        <span className="mr-2">{t('packs.export.size')}</span>
        <select className="rounded border border-space-border bg-space-surface p-1 text-gray-200" value={selected}
          onChange={(event) => setOverride(event.target.value)}>
          {original && <option value="native">{t('packs.export.native', { width: original.width, height: original.height })}</option>}
          {sizes.map((length) => <option key={length} value={length}>{dimensions(length)}</option>)}
        </select>
      </label>}
      {!fixedSize && size !== null && extentKm / size < sourceStepKm && <p className="text-amber-200">{t('packs.export.interpolated')}</p>}
      <label className="block">
        <span className="mr-2">{t('packs.export.format.label')}</span>
        <select className="rounded border border-space-border bg-space-surface p-1 text-gray-200" value={format}
          onChange={(event) => setFormat(event.target.value === 'tiff' ? 'tiff' : 'png')}>
          <option value="png">{t('packs.export.format.png')}</option>
          <option value="tiff">{t('packs.export.format.tiff')}</option>
        </select>
      </label>
      <p>{t(`packs.export.format.${format}Hint`)}</p>
      <button type="button" className="rounded border border-space-border bg-space-surface px-2 py-1 text-neon-cyan disabled:opacity-50"
        disabled={exporting} onClick={() => onDownload(fixedSize ? null : size, format)}>
        {exporting ? t('packs.export.exporting') : downloadLabel ?? t('packs.export.download')}
      </button>
      {failed && <p role="alert" className="text-red-300">{t('packs.export.failed')}</p>}
    </div>
  )
}
