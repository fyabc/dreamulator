/**
 * ElevationImportPanel — choose a heightmap, declare how its values become
 * metres, check the backend preview, then confirm.
 *
 * Nothing is written until the parent's `onConfirm` runs.  The preview goes
 * through the backend's own decoding and mapping (`/api/elevation-preview`),
 * so the coast, heights and statistics shown here are those the import will
 * produce.  A failed preview or import keeps the file and every typed value.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../api/client'
import {
  decodePreviewGrid,
  type ElevationImportResponse,
  type ElevationImportTarget,
  type ElevationMapping,
  type ElevationMappingMode,
  type ElevationPreviewGrid,
  type ElevationPreviewResponse,
  MODE_FIELDS,
  previewScale,
} from '../../api/elevationImport'
import ElevationPreviewCanvas from './ElevationPreviewCanvas'

/** Text-field state of a mapping, so half-typed numbers do not get lost. */
interface Draft {
  mode: ElevationMappingMode
  min_m: string
  max_m: string
  sea_level: string
  sea_level_m: string
  curve: 'linear' | 'gamma'
  gamma: string
  seafloor_m: string
}

type NumberField = 'min_m' | 'max_m' | 'sea_level' | 'sea_level_m' | 'gamma' | 'seafloor_m'

function toDraft(m: ElevationMapping): Draft {
  return {
    mode: m.mode,
    min_m: String(m.min_m),
    max_m: String(m.max_m),
    sea_level: String(m.sea_level),
    sea_level_m: String(m.sea_level_m),
    curve: m.curve,
    gamma: String(m.gamma),
    seafloor_m: String(m.seafloor_m),
  }
}

/** Parse a draft; returns the mapping or the field errors (i18n keys). */
function parseDraft(d: Draft): { mapping: ElevationMapping | null; errors: Partial<Record<NumberField, string>> } {
  const errors: Partial<Record<NumberField, string>> = {}
  const num = (key: NumberField): number => {
    const v = Number(d[key].trim())
    if (d[key].trim() === '' || !Number.isFinite(v)) errors[key] = 'error.notNumber'
    return v
  }
  const m: ElevationMapping = {
    mode: d.mode,
    min_m: num('min_m'),
    max_m: num('max_m'),
    sea_level: num('sea_level'),
    sea_level_m: num('sea_level_m'),
    curve: d.curve,
    gamma: num('gamma'),
    seafloor_m: num('seafloor_m'),
  }
  if (d.mode === 'range' && !errors.max_m && !errors.min_m && m.max_m <= m.min_m) errors.max_m = 'error.maxAboveMin'
  if (d.mode === 'threshold') {
    if (!errors.max_m && m.max_m <= 0) errors.max_m = 'error.maxPositive'
    if (!errors.sea_level && (m.sea_level < 0 || m.sea_level >= 1)) errors.sea_level = 'error.seaLevelFraction'
    if (!errors.seafloor_m && m.seafloor_m >= 0) errors.seafloor_m = 'error.seafloorNegative'
    if (d.curve === 'gamma' && !errors.gamma && m.gamma <= 0) errors.gamma = 'error.gammaPositive'
  }
  // Only the fields the chosen mode reads can block a preview.
  const used: Record<ElevationMappingMode, NumberField[]> = {
    range: ['min_m', 'max_m', 'sea_level_m'],
    threshold: d.curve === 'gamma' ? ['sea_level', 'max_m', 'gamma', 'seafloor_m'] : ['sea_level', 'max_m', 'seafloor_m'],
    metres: ['sea_level_m'],
  }
  const relevant: Partial<Record<NumberField, string>> = {}
  for (const key of used[d.mode]) if (errors[key]) relevant[key] = errors[key]
  return { mapping: Object.keys(relevant).length ? null : m, errors: relevant }
}

/** Grey levels per source format, used to show the sea threshold as a grey value. */
const GREY_LEVELS: Record<string, number> = {
  'png-8bit': 255,
  'png-converted': 255,
  'tiff-uint8': 255,
  'png-16bit': 65535,
  'tiff-uint16': 65535,
  'tiff-int16': 65535,
}

const PREVIEW_DEBOUNCE_MS = 350

/** Two mappings import the same way: same mode and same values for the fields it reads. */
function sameMapping(a: ElevationMapping, b: ElevationMapping): boolean {
  return a.mode === b.mode && MODE_FIELDS[a.mode].every((k) => a[k] === b[k])
}

interface Props {
  /** Existing map to import into; null for a world that does not exist yet. */
  target: ElevationImportTarget | null
  /** Performs the write.  Throwing keeps the panel state and shows the message. */
  onConfirm: (file: File, mapping: ElevationMapping, notes: string) => Promise<ElevationImportResponse>
  onCancel: () => void
  /** Extra inputs shown above the confirm button (e.g. the new world's name). */
  confirmExtras?: ReactNode
  /** When set, confirming is disabled and this reason is shown. */
  confirmBlockedReason?: string | null
  /** Called with the file name when the author picks a file. */
  onFileChosen?: (fileName: string) => void
}

export default function ElevationImportPanel({
  target,
  onConfirm,
  onCancel,
  confirmExtras,
  confirmBlockedReason,
  onFileChosen,
}: Props) {
  const { t } = useTranslation('importer')
  const fileInput = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [fileUrl, setFileUrl] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [preview, setPreview] = useState<ElevationPreviewResponse | null>(null)
  const [grid, setGrid] = useState<ElevationPreviewGrid | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [view, setView] = useState<'mapped' | 'source'>('mapped')
  const [showCoast, setShowCoast] = useState(true)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [notes, setNotes] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [confirmError, setConfirmError] = useState<string | null>(null)
  // What the shown preview was computed for, so an identical request is not repeated.
  const previewFor = useRef<{ file: File; targetKey: string } | null>(null)

  const parsed = useMemo(() => (draft ? parseDraft(draft) : null), [draft])
  const targetKey = target ? `${target.world}/${target.planetId}/${target.branch ?? ''}` : ''

  // Object URL for showing the original image (browsers display PNG, not TIFF).
  useEffect(() => {
    if (!file) return setFileUrl(null)
    const url = URL.createObjectURL(file)
    setFileUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  // Debounced backend preview whenever the file, mapping or target changes.
  const mappingKey = parsed?.mapping ? JSON.stringify(parsed.mapping) : draft ? 'invalid' : 'default'
  useEffect(() => {
    if (!file) return
    if (draft && !parsed?.mapping) return // field errors are shown inline
    const done = previewFor.current
    if (preview && parsed?.mapping && done?.file === file && done.targetKey === targetKey && sameMapping(preview.mapping, parsed.mapping)) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setPreviewing(true)
      api
        .previewElevationImport(file, parsed?.mapping ?? null, target, controller.signal)
        .then((res) => {
          previewFor.current = { file, targetKey }
          setPreview(res)
          setGrid(decodePreviewGrid(res.preview))
          setPreviewError(null)
          // First preview: show the defaults the backend chose in the form.
          setDraft((d) => d ?? toDraft(res.mapping))
        })
        .catch((e: unknown) => {
          if (controller.signal.aborted) return
          setPreviewError(e instanceof Error ? e.message : String(e))
        })
        .finally(() => {
          if (!controller.signal.aborted) setPreviewing(false)
        })
    }, draft ? PREVIEW_DEBOUNCE_MS : 0)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [file, mappingKey, targetKey])

  const chooseFile = (f: File) => {
    setFile(f)
    onFileChosen?.(f.name)
    previewFor.current = null
    setPreview(null)
    setGrid(null)
    setPreviewError(null)
    setConfirmError(null)
    // The draft is kept: an author retrying with a corrected file keeps their values.
  }

  const set = (patch: Partial<Draft>) => {
    setDraft((d) => (d ? { ...d, ...patch } : d))
    setConfirmError(null)
  }

  const previewMatchesDraft = !!(
    preview &&
    parsed?.mapping &&
    previewFor.current?.file === file &&
    previewFor.current.targetKey === targetKey &&
    sameMapping(preview.mapping, parsed.mapping)
  )
  const canConfirm = !!file && previewMatchesDraft && !previewing && !previewError && !confirming && !confirmBlockedReason

  const confirm = async () => {
    if (!file || !parsed?.mapping) return
    setConfirming(true)
    setConfirmError(null)
    try {
      await onConfirm(file, parsed.mapping, notes.trim())
    } catch (e) {
      setConfirmError(e instanceof Error ? e.message : String(e))
    } finally {
      setConfirming(false)
    }
  }

  const levels = preview ? GREY_LEVELS[preview.source_format] : undefined
  const scale = grid ? previewScale(grid) : null

  return (
    <div className="space-y-5" data-testid="elevation-import-panel">
      {/* Step 1: file */}
      <section className="glass-panel p-4">
        <h2 className="text-sm font-semibold text-gray-200 mb-1">{t('step.file')}</h2>
        <p className="text-xs text-gray-400">{t('help.file')}</p>
        <p className="text-xs text-gray-400 mt-1 mb-3">{t('help.regional')}</p>
        <input
          ref={fileInput}
          type="file"
          accept=".png,.tif,.tiff"
          className="hidden"
          data-testid="elevation-file-input"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) chooseFile(f)
            e.target.value = ''
          }}
        />
        <div className="flex items-center gap-3 flex-wrap">
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            className="px-3 py-1.5 text-sm rounded-lg bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25"
          >
            {file ? t('action.chooseOther') : t('action.chooseFile')}
          </button>
          {file && (
            <span className="text-sm text-gray-300">
              {file.name} <span className="text-gray-500">({formatBytes(file.size)})</span>
            </span>
          )}
        </div>
      </section>

      {file && (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
          {/* Step 2: declaration */}
          <section className="glass-panel p-4 lg:col-span-2 space-y-4">
            <div>
              <h2 className="text-sm font-semibold text-gray-200 mb-1">{t('step.mapping')}</h2>
              <p className="text-xs text-gray-400">{t('help.mapping')}</p>
            </div>
            {!draft && <p className="text-sm text-gray-400">{previewError ? '' : t('status.readingDefaults')}</p>}
            {draft && (
              <>
                <fieldset className="space-y-2">
                  {(['range', 'threshold', 'metres'] as const).map((mode) => (
                    <label key={mode} className={`block rounded-lg border p-2 cursor-pointer ${draft.mode === mode ? 'border-neon-cyan/50 bg-neon-cyan/5' : 'border-space-border'}`}>
                      <span className="flex items-center gap-2">
                        <input type="radio" name="mapping-mode" checked={draft.mode === mode} onChange={() => set({ mode })} data-testid={`mode-${mode}`} />
                        <span className="text-sm text-gray-200">{t(`mode.${mode}.label`)}</span>
                      </span>
                      <span className="block text-xs text-gray-400 mt-0.5 ml-5">{t(`mode.${mode}.desc`)}</span>
                    </label>
                  ))}
                </fieldset>

                {draft.mode === 'range' && (
                  <>
                    <NumberInput label={t('field.min_m')} unit="m" help={t('help.min_m')} value={draft.min_m} error={parsed?.errors.min_m} onChange={(v) => set({ min_m: v })} testId="field-min_m" />
                    <NumberInput label={t('field.max_m_range')} unit="m" help={t('help.max_m_range')} value={draft.max_m} error={parsed?.errors.max_m} onChange={(v) => set({ max_m: v })} testId="field-max_m" />
                    <NumberInput label={t('field.sea_level_m')} unit="m" help={t('help.sea_level_m')} value={draft.sea_level_m} error={parsed?.errors.sea_level_m} onChange={(v) => set({ sea_level_m: v })} testId="field-sea_level_m" />
                  </>
                )}
                {draft.mode === 'threshold' && (
                  <>
                    <NumberInput
                      label={t('field.sea_level')}
                      unit={t('unit.fraction')}
                      help={t('help.sea_level')}
                      value={draft.sea_level}
                      error={parsed?.errors.sea_level}
                      onChange={(v) => set({ sea_level: v })}
                      testId="field-sea_level"
                      note={levels && parsed?.mapping ? t('note.greyLevel', { grey: Math.floor(parsed.mapping.sea_level * levels), levels }) : undefined}
                    />
                    <NumberInput label={t('field.max_m_threshold')} unit="m" help={t('help.max_m_threshold')} value={draft.max_m} error={parsed?.errors.max_m} onChange={(v) => set({ max_m: v })} testId="field-max_m" />
                    <NumberInput label={t('field.seafloor_m')} unit="m" help={t('help.seafloor_m')} value={draft.seafloor_m} error={parsed?.errors.seafloor_m} onChange={(v) => set({ seafloor_m: v })} testId="field-seafloor_m" />
                    <button type="button" className="text-xs text-neon-cyan/80 hover:underline" onClick={() => setShowAdvanced((s) => !s)}>
                      {showAdvanced ? t('action.hideAdvanced') : t('action.showAdvanced')}
                    </button>
                    {showAdvanced && (
                      <div className="space-y-2 border-l border-space-border pl-3">
                        <label className="block text-sm text-gray-300">
                          {t('field.curve')}
                          <select className="ml-2 bg-space-surface border border-space-border rounded px-2 py-0.5 text-sm" value={draft.curve} onChange={(e) => set({ curve: e.target.value as Draft['curve'] })}>
                            <option value="linear">{t('curve.linear')}</option>
                            <option value="gamma">{t('curve.gamma')}</option>
                          </select>
                        </label>
                        <p className="text-xs text-gray-500">{t('help.curve')}</p>
                        {draft.curve === 'gamma' && (
                          <NumberInput label={t('field.gamma')} unit="" help={t('help.gamma')} value={draft.gamma} error={parsed?.errors.gamma} onChange={(v) => set({ gamma: v })} testId="field-gamma" />
                        )}
                      </div>
                    )}
                  </>
                )}
                {draft.mode === 'metres' && (
                  <NumberInput label={t('field.sea_level_m')} unit="m" help={t('help.sea_level_m')} value={draft.sea_level_m} error={parsed?.errors.sea_level_m} onChange={(v) => set({ sea_level_m: v })} testId="field-sea_level_m" />
                )}
                {preview && (
                  <p className="text-xs text-gray-500">{t(`defaults.${preview.mapping_source}`)}</p>
                )}
              </>
            )}
          </section>

          {/* Step 3: preview and report */}
          <section className="glass-panel p-4 lg:col-span-3 space-y-3">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-sm font-semibold text-gray-200 mr-auto">{t('step.preview')}</h2>
              {previewing && <span className="text-xs text-gray-400" data-testid="preview-busy">{t('status.previewing')}</span>}
              <div className="flex rounded-lg border border-space-border overflow-hidden text-xs">
                {(['mapped', 'source'] as const).map((v) => (
                  <button key={v} type="button" onClick={() => setView(v)} className={`px-2 py-1 ${view === v ? 'bg-neon-cyan/15 text-neon-cyan' : 'text-gray-400'}`}>
                    {t(`view.${v}`)}
                  </button>
                ))}
              </div>
              {view === 'mapped' && (
                <label className="text-xs text-gray-400 flex items-center gap-1">
                  <input type="checkbox" checked={showCoast} onChange={(e) => setShowCoast(e.target.checked)} />
                  {t('view.coast')}
                </label>
              )}
            </div>

            {previewError && (
              <div className="rounded border border-red-700/40 bg-red-900/20 p-3 text-sm text-red-300" data-testid="preview-error">
                <p>{t('error.previewFailed')}</p>
                <p className="text-xs mt-1 break-words">{localiseError(previewError, t)}</p>
                <p className="text-xs mt-1 text-red-200/80">{t('error.previewKeepsValues')}</p>
              </div>
            )}

            {view === 'mapped' && grid && (
              <>
                <ElevationPreviewCanvas grid={grid} showCoast={showCoast} />
                {scale && (
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-400">
                    <span>
                      <LegendSwatch from="#0c1e4a" to="#5c9acd" /> {t('legend.sea', { min: fmtM(scale.seaMin), max: fmtM(scale.seaMax) })}
                    </span>
                    <span>
                      <LegendSwatch from="#3e8048" to="#ececec" /> {t('legend.land', { min: fmtM(scale.landMin), max: fmtM(scale.landMax) })}
                    </span>
                    {showCoast && (
                      <span>
                        <LegendSwatch from="#ffee58" to="#ffee58" /> {t('legend.coast')}
                      </span>
                    )}
                  </div>
                )}
                <p className="text-xs text-gray-500">
                  {t('preview.gridNote', { w: grid.width, h: grid.height, ow: preview?.output_resolution[0], oh: preview?.output_resolution[1] })}
                </p>
              </>
            )}
            {view === 'source' && preview && fileUrl && (
              <SourceImage url={fileUrl} isPng={/\.png$/i.test(file.name)} />
            )}

            {preview && <ImportReport preview={preview} />}
          </section>
        </div>
      )}

      {/* Step 4: confirm */}
      <section className="glass-panel p-4 space-y-3">
        <h2 className="text-sm font-semibold text-gray-200">{t('step.confirm')}</h2>
        {confirmExtras}
        <label className="block text-sm text-gray-300">
          {t('field.notes')}
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            placeholder={t('help.notes')}
            className="mt-1 w-full bg-space-surface border border-space-border rounded px-2 py-1 text-sm text-gray-200"
          />
        </label>
        <p className="text-xs text-gray-400">{t('help.confirm')}</p>
        {confirmBlockedReason && <p className="text-xs text-amber-300" data-testid="confirm-blocked">{confirmBlockedReason}</p>}
        {file && !previewMatchesDraft && !previewError && <p className="text-xs text-gray-500">{t('status.waitPreview')}</p>}
        {confirmError && (
          <div className="rounded border border-red-700/40 bg-red-900/20 p-3 text-sm text-red-300" data-testid="confirm-error">
            <p>{t('error.importFailed')}</p>
            <p className="text-xs mt-1 break-words">{localiseError(confirmError, t)}</p>
            <p className="text-xs mt-1 text-red-200/80">{t('error.previewKeepsValues')}</p>
          </div>
        )}
        <div className="flex gap-3">
          <button
            type="button"
            onClick={() => void confirm()}
            disabled={!canConfirm}
            data-testid="confirm-import"
            className="px-4 py-2 rounded-lg text-sm font-medium bg-neon-cyan/20 text-neon-cyan border border-neon-cyan/40 hover:bg-neon-cyan/30 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {confirming ? t('status.importing') : t('action.confirm')}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={confirming}
            data-testid="cancel-import"
            className="px-4 py-2 rounded-lg text-sm text-gray-300 border border-space-border hover:text-white disabled:opacity-40"
          >
            {t('action.cancel')}
          </button>
        </div>
      </section>
    </div>
  )
}

function NumberInput(props: {
  label: string
  unit: string
  help: string
  value: string
  error?: string
  note?: string
  testId: string
  onChange: (v: string) => void
}) {
  const { t } = useTranslation('importer')
  return (
    <label className="block">
      <span className="text-sm text-gray-300">{props.label}</span>
      <span className="flex items-center gap-2 mt-0.5">
        <input
          type="text"
          inputMode="decimal"
          value={props.value}
          onChange={(e) => props.onChange(e.target.value)}
          data-testid={props.testId}
          className={`w-36 bg-space-surface border rounded px-2 py-1 text-sm text-gray-100 ${props.error ? 'border-red-500/70' : 'border-space-border'}`}
        />
        {props.unit && <span className="text-xs text-gray-400">{props.unit}</span>}
        {props.note && <span className="text-xs text-gray-500">{props.note}</span>}
      </span>
      {props.error && <span className="block text-xs text-red-300 mt-0.5">{t(props.error)}</span>}
      <span className="block text-xs text-gray-500 mt-0.5">{props.help}</span>
    </label>
  )
}

function ImportReport({ preview }: { preview: ElevationPreviewResponse }) {
  const { t } = useTranslation('importer')
  const [sw, sh] = preview.source_resolution
  const [ow, oh] = preview.output_resolution
  const rows: [string, string][] = [
    [t('report.format'), preview.source_format],
    [t('report.sourceSize'), `${sw} × ${sh}`],
    [
      t('report.outputSize'),
      `${ow} × ${oh} — ${t(preview.resolution_from === 'map' ? 'report.sizeFromMap' : 'report.sizeFromSource')}${preview.was_resampled ? t('report.resampled') : ''}`,
    ],
    [t('report.range'), `${fmtM(preview.range_m[0])} – ${fmtM(preview.range_m[1])}`],
    [t('report.landArea'), pct(preview.land_area_fraction)],
    [t('report.landPixels'), pct(preview.land_fraction)],
  ]
  if (preview.level_step_m) {
    rows.push([t('report.levelStep'), t('report.levelStepValue', { coast: preview.level_step_m.coast.toFixed(1), max: preview.level_step_m.max.toFixed(1) })])
  }
  return (
    <div className="space-y-2" data-testid="import-report">
      <table className="w-full text-sm">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k} className="border-b border-space-border/50 last:border-0">
              <td className="py-1 pr-3 text-gray-400 align-top whitespace-nowrap">{k}</td>
              <td className="py-1 text-gray-200">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-gray-500">{t('report.landNote')}</p>
      {preview.seafloor_assumed && (
        <p className="text-xs text-amber-300" data-testid="seafloor-assumed">
          {t('report.seafloorAssumed', { depth: fmtM(preview.mapping.seafloor_m) })}
        </p>
      )}
      {preview.warnings.length > 0 && (
        <ul className="text-xs text-amber-300 list-disc pl-5 space-y-0.5" data-testid="import-warnings">
          {preview.warnings.map((w) => (
            <li key={w}>{localiseWarning(w, t)}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Plain-language versions of the backend's known warnings; unknown ones pass through. */
function localiseWarning(w: string, t: (key: string, opts?: Record<string, unknown>) => string): string {
  const eight = /^8-bit input: (\d+) levels; one level is ([\d.]+) m at the coast and up to ([\d.]+) m/.exec(w)
  if (eight) return t('warning.eightBit', { levels: eight[1], coast: eight[2], max: eight[3] })
  if (w.startsWith('8-bit input')) return t('warning.eightBitPlain')
  return w
}

/** Plain-language versions of known backend input errors; unknown ones pass through. */
function localiseError(e: string, t: (key: string, opts?: Record<string, unknown>) => string): string {
  const aspect = /^Global heightmap must be 2:1 \(received (\d+)x(\d+)\)$/.exec(e)
  if (aspect) return t('error.aspect', { w: aspect[1], h: aspect[2] })
  const size = /^Global heightmap dimensions exceed (\d+)x(\d+)$/.exec(e)
  if (size) return t('error.dimensions', { w: size[1], h: size[2] })
  const bytes = /^Global heightmap file exceeds (\d+) MiB$/.exec(e)
  if (bytes) return t('error.fileSize', { mib: bytes[1] })
  if (e === 'Cannot read a PNG or TIFF heightmap') return t('error.unreadable')
  return e
}

function SourceImage({ url, isPng }: { url: string; isPng: boolean }) {
  const { t } = useTranslation('importer')
  const [failed, setFailed] = useState(false)
  if (!isPng || failed) return <p className="text-sm text-gray-400">{t('view.sourceUnavailable')}</p>
  return (
    <div>
      <img src={url} alt="" className="w-full rounded border border-space-border" onError={() => setFailed(true)} />
      <p className="text-xs text-gray-500 mt-1">{t('view.sourceNote')}</p>
    </div>
  )
}

function LegendSwatch({ from, to }: { from: string; to: string }) {
  return <span className="inline-block w-6 h-2 align-middle rounded-sm mr-1" style={{ background: `linear-gradient(to right, ${from}, ${to})` }} />
}

function fmtM(m: number): string {
  return Number.isFinite(m) ? `${Math.round(m).toLocaleString()} m` : '—'
}

function pct(x: number): string {
  return `${(x * 100).toFixed(1)}%`
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
