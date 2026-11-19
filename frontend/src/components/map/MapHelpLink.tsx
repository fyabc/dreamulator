import { Link } from 'react-router-dom'

export default function MapHelpLink({ section, label }: { section: string; label: string }) {
  return (
    <Link to={`/help#${section}`} target="_blank" rel="noopener noreferrer" title={label} aria-label={label}
      className="inline-flex size-7 shrink-0 items-center justify-center rounded-full border border-space-border bg-space-surface font-bold text-gray-300 hover:border-neon-cyan/50 hover:text-neon-cyan">
      <span aria-hidden="true">?</span>
    </Link>
  )
}
