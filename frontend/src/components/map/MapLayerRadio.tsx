import type { ReactNode } from 'react'

export default function MapLayerRadio({ name, checked, disabled, title, onChange, onClick, label, dimmed, children }: {
  name: string; checked: boolean; disabled?: boolean; title?: string; onChange: () => void
  onClick?: () => void; label: string; dimmed?: boolean; children?: ReactNode
}) {
  return (
    <label className={`flex items-center gap-1.5 ${disabled ? 'opacity-50' : 'cursor-pointer'}`} title={title}>
      <input type="radio" name={name} checked={checked} disabled={disabled} onChange={onChange} onClick={onClick}
        className="h-3.5 w-3.5 accent-neon-cyan cursor-pointer" />
      <span className={`text-xs ${checked ? 'text-gray-200' : 'text-gray-500'} ${dimmed ? 'opacity-50' : ''}`}>{label}</span>
      {children}
    </label>
  )
}
