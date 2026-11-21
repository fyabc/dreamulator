import type { ReactNode } from 'react'

interface Props {
  children: ReactNode
  tools: ReactNode
  toolsLabel: string
  status?: ReactNode
}

export default function RegionMapWorkspace({ children, tools, toolsLabel, status }: Props) {
  return (
    <div className="bg-space-bg md:grid md:min-h-0 md:flex-1 md:grid-cols-[15rem_minmax(0,1fr)]">
      <div className="flex min-w-0 flex-col md:col-start-2 md:row-start-1 md:min-h-0">
        <div className="relative isolate h-[clamp(18rem,56dvh,36rem)] md:h-auto md:min-h-0 md:flex-1">
          {children}
        </div>
        {status}
      </div>
      <aside aria-label={toolsLabel}
        className="min-w-0 space-y-3 border-t border-space-border bg-space-panel p-3 text-xs text-gray-400 md:col-start-1 md:row-start-1 md:overflow-auto md:border-r md:border-t-0">
        {tools}
      </aside>
    </div>
  )
}
