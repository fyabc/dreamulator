/**
 * ProbePanel — the click-pin readout: cell values from /api/packs probe with
 * legend-translated biome/köppen names, water-mask chips, river regime, and
 * export-ready coordinate copy buttons (the strings the CLI accepts).
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { LonLat } from '../map/utils/mapCoords'
import type { PackMeta, ProbeResult } from './types'

interface ProbePanelProps {
  point: LonLat | null
  probe: ProbeResult | null
  loading: boolean
  error: string | null
  meta: PackMeta | null
  spanKm: number | null
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <span className="text-xs text-gray-500">{label}</span>
      <span className="text-xs text-gray-200 font-mono text-right">{children}</span>
    </div>
  )
}

function CopyButton({ text, title }: { text: string; title: string }) {
  const { t } = useTranslation('map')
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      title={title}
      onClick={() => {
        navigator.clipboard
          .writeText(text)
          .then(() => {
            setCopied(true)
            window.setTimeout(() => setCopied(false), 1200)
          })
          .catch(() => undefined)
      }}
      className={[
        'px-2 py-1 rounded text-xs font-mono border transition-colors',
        copied
          ? 'border-neon-cyan/60 text-neon-cyan'
          : 'border-space-border text-gray-400 hover:text-gray-200 hover:border-gray-500',
      ].join(' ')}
    >
      {copied ? t('packs.copied') : text}
    </button>
  )
}

function Chip({ on, label }: { on: boolean | null; label: string }) {
  if (on === null) return null
  return (
    <span
      className={[
        'px-1.5 py-0.5 rounded text-xs',
        on ? 'bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/40' : 'text-gray-600 border border-space-border',
      ].join(' ')}
    >
      {label}
      {on ? ' ✓' : ''}
    </span>
  )
}

export default function ProbePanel({ point, probe, loading, error, meta, spanKm }: ProbePanelProps) {
  const { t } = useTranslation('map')

  if (!point) {
    return (
      <div className="bg-space-panel/90 border border-space-border rounded-lg p-3 text-xs text-gray-500">
        {t('packs.probePrompt')}
      </div>
    )
  }

  const biomeName = (code: number | null): string => {
    if (code === null) return '—'
    const legend = meta?.input.climate?.biome?.legend
    return legend?.[String(code)] ?? String(code)
  }
  const koppenName = (code: number | null): string => {
    if (code === null) return '—'
    const legend = meta?.input.climate?.koppen?.legend
    return legend?.[String(code)] ?? String(code)
  }
  const regimeLabel = (regime: number | null): string => {
    if (regime === null) return '—'
    return regime === 0 ? t('packs.regime.perennial') : t('packs.regime.nonPerennial')
  }

  return (
    <div className="bg-space-panel/90 border border-space-border rounded-lg p-3 space-y-2 backdrop-blur-sm min-w-56">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-semibold text-neon-cyan">{t('packs.probeTitle')}</span>
        <span className="text-xs text-gray-400 font-mono">
          {point.lon.toFixed(4)}°, {point.lat.toFixed(4)}°
        </span>
      </div>

      {loading && <div className="text-xs text-gray-500">{t('packs.probing')}</div>}
      {error && <div className="text-xs text-red-400">{error}</div>}

      {probe && !loading && (
        <>
          <Row label={t('packs.field.height')}>
            <span className={probe.height_m !== null && probe.height_m >= 0 ? 'text-green-400' : 'text-blue-400'}>
              {probe.height_m === null ? '—' : `${probe.height_m >= 0 ? '+' : ''}${probe.height_m.toFixed(1)} m`}
              {probe.height_source ? ` (${probe.height_source})` : ''}
            </span>
          </Row>
          <Row label={t('packs.field.biome')}>{biomeName(probe.biome_code)}</Row>
          <Row label={t('packs.field.koppen')}>{koppenName(probe.koppen_code)}</Row>
          <Row label={t('packs.field.cell')}>
            [{probe.row}, {probe.col}] @ {probe.res.w}×{probe.res.h}
          </Row>
          {probe.river_flow_accum !== null && (
            <Row label={t('packs.field.riverFlow')}>
              {probe.river_flow_accum.toFixed(0)} · {regimeLabel(probe.river_regime)}
            </Row>
          )}
          <div className="flex flex-wrap gap-1.5 pt-1">
            <Chip on={probe.river} label={t('packs.chip.river')} />
            <Chip on={probe.lake} label={t('packs.chip.lake')} />
            <Chip on={probe.sea_water} label={t('packs.chip.sea')} />
          </div>
        </>
      )}

      <div className="flex flex-col gap-1.5 pt-1">
        <CopyButton
          text={`--lat ${point.lat.toFixed(4)} --lon ${point.lon.toFixed(4)}${spanKm ? ` --span-km ${Math.round(spanKm)}` : ''}`}
          title={t('packs.copyCliTitle')}
        />
        <CopyButton
          text={`${point.lat.toFixed(4)}, ${point.lon.toFixed(4)}`}
          title={t('packs.copyPlainTitle')}
        />
      </div>
    </div>
  )
}
