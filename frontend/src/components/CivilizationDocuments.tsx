import { useState, useMemo, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../api/client'

interface CivilizationDocumentsProps {
  worldName: string
  branch: string | null
}

/** Category labels for grouping documents in the sidebar. */
const CATEGORY_ORDER: [string, string][] = [
  ['overview', '总览'],
  ['timeline', '编年史'],
  ['thematic', '专题'],
  ['geopolitical', '地缘政治'],
  ['microhistory', '微观史'],
  // Fallback for any other type
  ['', '其他'],
]

function getCategory(type: string): string {
  for (const [key] of CATEGORY_ORDER) {
    if (key && type.startsWith(key)) return key
  }
  // Special handling: _overview is always "overview"
  return type || ''
}

export default function CivilizationDocuments({
  worldName,
  branch,
}: CivilizationDocumentsProps) {
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null)
  const [navOpen, setNavOpen] = useState(false)

  // Fetch document list
  const { data: documents } = useQuery({
    queryKey: ['civ-documents', worldName, branch],
    queryFn: () => api.listCivilizationDocuments(worldName, branch),
    enabled: !!worldName,
    retry: false,
  })

  // Auto-select _overview.md on first load
  const effectiveDoc = useMemo(() => {
    if (selectedDoc) return selectedDoc
    if (!documents || documents.length === 0) return null
    if (documents.some((d: any) => d.filename === '_overview.md')) return '_overview.md'
    return documents[0].filename
  }, [selectedDoc, documents])

  // Fetch selected document content
  const { data: activeDoc } = useQuery({
    queryKey: ['civ-document', worldName, effectiveDoc, branch],
    queryFn: () => api.getCivilizationDocument(worldName, effectiveDoc!, branch),
    enabled: !!worldName && !!effectiveDoc,
    retry: false,
  })

  // Group documents by category
  const grouped = useMemo(() => {
    if (!documents?.length) return []
    const groups: Record<string, any[]> = {}
    for (const doc of documents) {
      const cat = getCategory(doc.type)
      if (!groups[cat]) groups[cat] = []
      groups[cat].push(doc)
    }
    return CATEGORY_ORDER.filter(([key]) => groups[key]).map(([key, label]) => ({
      key,
      label,
      docs: groups[key],
    }))
  }, [documents])

  // Handle cross-reference clicks (links like `filename.md`)
  const handleLinkClick = useCallback(
    (e: React.MouseEvent<HTMLAnchorElement>) => {
      const href = e.currentTarget.getAttribute('href') || ''
      // Match cross-references to other .md files
      const mdMatch = href.match(/^([a-zA-Z0-9_-]+\.md)$/)
      if (mdMatch && documents?.some((d: any) => d.filename === mdMatch[1])) {
        e.preventDefault()
        setSelectedDoc(mdMatch[1])
      }
    },
    [documents],
  )

  if (!documents?.length) return null

  return (
    <div className="min-h-[600px]">
      {/* Mobile: TOC toggle button */}
      <button
        onClick={() => setNavOpen(!navOpen)}
        className="lg:hidden flex items-center gap-2 mb-3 px-3 py-2 rounded-lg text-sm
          bg-space-surface/60 text-gray-300 border border-space-border hover:bg-space-surface/80 transition-colors"
      >
        <span>📑</span>
        <span>目录</span>
        <span className="text-gray-500 text-xs ml-auto">
          {effectiveDoc ? (documents.find((d: any) => d.filename === effectiveDoc)?.title || effectiveDoc) : '选择文档'}
        </span>
        <span className="text-gray-500">{navOpen ? '▲' : '▼'}</span>
      </button>

      {/* Mobile nav backdrop */}
      {navOpen && (
        <div
          className="lg:hidden fixed inset-0 bg-black/50 z-40"
          onClick={() => setNavOpen(false)}
        />
      )}

      <div className="flex gap-4">
        {/* Sidebar — drawer on mobile, fixed on desktop */}
        <nav className={`
          fixed lg:static inset-y-0 left-0 z-50 lg:z-auto
          w-64 lg:w-56 shrink-0 bg-gray-900 lg:bg-transparent
          space-y-4 overflow-y-auto max-h-[80vh] lg:max-h-none
          p-4 lg:p-0 lg:sticky lg:top-4 lg:self-start
          transition-transform duration-200 ease-in-out
          ${navOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        `}>
          {/* Mobile close */}
          <div className="lg:hidden flex justify-between items-center mb-3 pb-2 border-b border-space-border">
            <span className="text-sm font-semibold text-gray-300">文档目录</span>
            <button
              onClick={() => setNavOpen(false)}
              className="text-gray-400 hover:text-white text-lg"
            >
              ✕
            </button>
          </div>

          {grouped.map((group) => (
            <div key={group.key}>
              <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5 px-1">
                {group.label}
              </h4>
              <ul className="space-y-0.5">
                {group.docs.map((doc: any) => (
                  <li key={doc.filename}>
                    <button
                      onClick={() => { setSelectedDoc(doc.filename); setNavOpen(false) }}
                      className={`w-full text-left px-2.5 py-1.5 rounded text-sm transition-colors ${
                        effectiveDoc === doc.filename
                          ? 'bg-neon-cyan/10 text-neon-cyan border-l-2 border-neon-cyan'
                          : 'text-gray-400 hover:text-gray-200 hover:bg-space-surface/60'
                      }`}
                    >
                      {doc.title || doc.filename}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>

        {/* Content */}
        <div className="flex-1 min-w-0 glass-panel p-4 sm:p-6 overflow-auto">
        {activeDoc ? (
          <article className="prose prose-invert prose-sm max-w-none
            prose-headings:text-neon-cyan prose-headings:font-semibold
            prose-h1:text-xl prose-h1:neon-glow-subtle prose-h1:mb-4 prose-h1:pb-2 prose-h1:border-b prose-h1:border-space-border
            prose-h2:text-lg prose-h2:text-neon-cyan/90 prose-h2:mt-6 prose-h2:mb-3
            prose-h3:text-base prose-h3:text-amber-300 prose-h3:mt-4 prose-h3:mb-2
            prose-h4:text-sm prose-h4:text-amber-400/80 prose-h4:mt-3 prose-h4:mb-1.5
            prose-p:text-gray-300 prose-p:leading-relaxed prose-p:my-2
            prose-li:text-gray-300 prose-li:leading-relaxed
            prose-strong:text-gray-100
            prose-em:text-gray-400
            prose-a:text-neon-cyan prose-a:no-underline hover:prose-a:underline
            prose-code:text-amber-300 prose-code:bg-space-surface/60 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-xs
            prose-pre:bg-space-surface/80 prose-pre:border prose-pre:border-space-border prose-pre:rounded-lg
            prose-blockquote:border-l-neon-cyan/40 prose-blockquote:text-gray-400 prose-blockquote:italic
            prose-hr:border-space-border
            [&_table]:w-full [&_table]:text-sm [&_table]:border-collapse [&_table]:my-3
            [&_th]:text-left [&_th]:text-amber-300 [&_th]:font-semibold [&_th]:px-3 [&_th]:py-2 [&_th]:border-b [&_th]:border-space-border [&_th]:bg-space-surface/40
            [&_td]:px-3 [&_td]:py-2 [&_td]:border-b [&_td]:border-space-border/40 [&_td]:text-gray-300
            [&_tr:hover_td]:bg-space-surface/20
          ">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children, ...props }) => (
                  <a href={href} onClick={handleLinkClick} {...props}>
                    {children}
                  </a>
                ),
                // Auto-link inline code like `territory.md` to document navigation
                code: ({ className, children, ...props }) => {
                  const text = String(children).replace(/\n$/, '')
                  const isDocRef = /^[a-zA-Z0-9_-]+\.md$/.test(text)
                  const docExists = isDocRef && documents?.some((d: any) => d.filename === text)
                  if (docExists) {
                    return (
                      <button
                        onClick={() => setSelectedDoc(text)}
                        className="text-neon-cyan hover:underline cursor-pointer bg-space-surface/60 px-1 py-0.5 rounded text-xs font-mono"
                      >
                        {text}
                      </button>
                    )
                  }
                  return (
                    <code className={className} {...props}>
                      {children}
                    </code>
                  )
                },
              }}
            >
              {activeDoc.content}
            </ReactMarkdown>
          </article>
        ) : (
          <div className="flex items-center justify-center h-64 text-gray-500">
            选择左侧文档
          </div>
        )}
      </div>
      </div>
    </div>
  )
}
