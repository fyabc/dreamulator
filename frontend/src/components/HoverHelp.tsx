import { useState, type ReactNode } from 'react'
import AtlasIcon from './AtlasIcon'

/** Small help button with a hover/focus tooltip. */
export default function HoverHelp({ label, children, align = 'left', above = false }: {
  label: string
  children: ReactNode
  align?: 'left' | 'right'
  above?: boolean
}) {
  const [open, setOpen] = useState(false)
  return (
    <span className="relative inline-flex"
      onPointerEnter={event => { if (event.pointerType === 'mouse') setOpen(true) }}
      onPointerLeave={event => { if (event.pointerType === 'mouse') setOpen(false) }}
      onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false)
      }}>
      <button type="button" aria-label={label} aria-expanded={open}
        onClick={() => setOpen(value => !value)}
        onFocus={() => setOpen(true)}
        onKeyDown={event => { if (event.key === 'Escape') setOpen(false) }}
        className="inline-grid size-5 place-items-center rounded text-gray-400 hover:text-neon-cyan focus-visible:text-neon-cyan focus-visible:outline focus-visible:outline-2 focus-visible:outline-neon-cyan">
        <AtlasIcon name="help" className="size-3.5" />
      </button>
      {open && <span role="tooltip" className={`absolute z-50 w-64 rounded border border-space-border bg-space-panel px-2.5 py-2 text-xs font-normal leading-relaxed text-gray-200 shadow-xl ${above ? 'bottom-full mb-1' : 'top-full mt-1'} ${align === 'right' ? 'right-0' : 'left-0'}`}>
        {children}
      </span>}
    </span>
  )
}
