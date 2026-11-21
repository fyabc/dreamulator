import { useEffect, useRef, type ReactNode } from 'react'

export interface TimelineItem {
  id: string
  label: ReactNode
  state: 'pending' | 'active' | 'done' | 'failed' | 'skipped'
  status?: string
  detail?: ReactNode
  substep?: boolean
}

export default function ProgressTimeline({ items, titleId, current, follow }: {
  items: TimelineItem[]
  titleId: string
  current?: string
  follow: boolean
}) {
  const viewport = useRef<HTMLOListElement>(null)
  const target = useRef<HTMLLIElement>(null)

  useEffect(() => {
    if (!follow || !target.current || !viewport.current) return
    viewport.current.scrollTo({ top: Math.max(0, target.current.offsetTop - viewport.current.clientHeight / 4) })
  }, [current, follow])

  return <ol ref={viewport} role="list" aria-labelledby={titleId} tabIndex={0}
    className="relative max-h-36 overflow-y-auto rounded border border-space-border bg-space-bg py-1.5 focus-visible:outline focus-visible:outline-neon-cyan motion-safe:scroll-smooth sm:max-h-52 [scrollbar-color:#526c70_transparent]">
    {items.map(({ id, label, state, status, detail, substep }, index) => {
      const done = state === 'done'
      const active = state === 'active'
      const failed = state === 'failed'
      return <li key={id} ref={id === current ? target : undefined} aria-current={id === current && active ? 'step' : undefined}
        className="relative grid min-h-8 grid-cols-[1rem_minmax(0,1fr)] items-start gap-2 pr-2 pl-2.5">
        {index < items.length - 1 && <span aria-hidden="true"
          className={`absolute bottom-[-.9rem] left-[1.09rem] top-3.5 w-px motion-safe:transition-colors ${done ? 'bg-neon-cyan/55' : 'bg-space-border'}`} />}
        <span aria-hidden="true" className={`relative grid place-items-center justify-self-center rounded-full border motion-safe:transition-colors ${substep ? 'mt-2 size-3' : 'mt-1.5 size-4'} ${
          done ? 'border-neon-cyan bg-neon-cyan text-space-bg' : failed ? 'border-red-300 bg-space-bg text-red-300' : active ? 'border-neon-cyan bg-space-bg text-neon-cyan' : 'border-space-border bg-space-bg text-gray-500'
        }`}>
          {done || failed ? <svg viewBox="0 0 16 16" className={substep ? 'size-2.5' : 'size-3'} fill="none" stroke="currentColor"
            strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <path d={failed ? 'm5 5 6 6m0-6-6 6' : 'm3.5 8 3 3 6-6'} />
          </svg> : <span className={`${active ? 'size-1.5' : 'size-1'} rounded-full bg-current`} />}
        </span>
        <div className={`py-1.5 leading-4 ${substep ? 'pl-2 text-xs' : ''} ${failed ? 'text-red-200' : active ? 'font-semibold text-neon-cyan' : done ? 'text-gray-200' : 'text-gray-400'}`}>
          <div className="flex flex-wrap justify-between gap-x-3 gap-y-0.5">
            <span>{label}</span>
            {status && <span className="text-xs font-normal">{status}</span>}
          </div>
          {detail && <div className="mt-1 space-y-0.5 font-normal tabular-nums text-gray-300">{detail}</div>}
        </div>
      </li>
    })}
  </ol>
}
