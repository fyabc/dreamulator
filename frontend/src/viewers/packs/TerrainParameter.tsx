import { useId } from 'react'

export function TerrainParameter({ label, help, value, onChange, placeholder, min, max, step = 'any', invalid = false }: {
  label: string
  help: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  min?: number
  max?: number
  step?: number | 'any'
  invalid?: boolean
}) {
  const helpId = useId()
  return <div className="space-y-1">
    <label className="flex items-center justify-between gap-1" title={help}>
      <span>{label}</span>
      <input type="number" min={min} max={max} step={step} inputMode={step === 1 ? 'numeric' : 'decimal'}
        className="w-24 shrink-0 rounded border border-space-border bg-space-surface p-1 text-right text-gray-200"
        value={value} placeholder={placeholder} aria-describedby={helpId} aria-invalid={invalid}
        onChange={(event) => onChange(event.currentTarget.value)} />
    </label>
    <p id={helpId} className={invalid ? 'text-amber-200' : undefined}>{help}</p>
  </div>
}
