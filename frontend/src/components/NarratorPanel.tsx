import { useCallback, useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import { narrateWorldStream, NarrateUsage } from '../api/client'

interface NarratorPanelProps {
  worldName: string
  branch?: string | null
}

export default function NarratorPanel({ worldName, branch }: NarratorPanelProps) {
  const [narration, setNarration] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [usage, setUsage] = useState<NarrateUsage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<(() => void) | null>(null)

  // Clear narration when branch changes
  useEffect(() => {
    setNarration('')
    setUsage(null)
    setError(null)
  }, [branch])

  const handleGenerate = useCallback(() => {
    setNarration('')
    setUsage(null)
    setError(null)
    setIsStreaming(true)

    const abort = narrateWorldStream(
      worldName,
      (text) => setNarration((prev) => prev + text),
      (u) => {
        setUsage(u)
        setIsStreaming(false)
      },
      (err) => {
        setError(err)
        setIsStreaming(false)
      },
      { branch: branch ?? undefined },
    )

    abortRef.current = abort
  }, [worldName, branch])

  const handleStop = useCallback(() => {
    abortRef.current?.()
    abortRef.current = null
    setIsStreaming(false)
  }, [])

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex items-center gap-3">
        <div className="relative group">
          <button
            onClick={handleGenerate}
            disabled={isStreaming}
            className="px-4 py-2 rounded-lg font-medium transition-all bg-neon-cyan/15 text-neon-cyan border border-neon-cyan/30 hover:bg-neon-cyan/25 disabled:opacity-50 flex items-center gap-2"
          >
            <span>⚠️</span>
            <span>{isStreaming ? '生成中...' : narration ? '重新生成' : '生成叙述'}</span>
          </button>
          <div className="absolute bottom-full left-0 mb-2 px-3 py-2 bg-space-surface border border-yellow-500/30 rounded-lg text-xs text-yellow-300 whitespace-nowrap opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all pointer-events-none shadow-lg">
            警告：此操作将调用大语言模型 API，会消耗 token
          </div>
        </div>
        {isStreaming && (
          <button
            onClick={handleStop}
            className="px-4 py-2 rounded-lg font-medium transition-all bg-red-900/20 text-red-400 border border-red-500/30 hover:bg-red-900/30"
          >
            停止
          </button>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 rounded-lg border bg-red-900/30 border-red-500/20">
          <p className="text-red-300 text-sm">{error}</p>
        </div>
      )}

      {/* Narration content */}
      {(narration || isStreaming) && (
        <div className="glass-panel p-6">
          {narration ? (
            <div className="narrator-prose">
              <Markdown>{narration}</Markdown>
            </div>
          ) : (
            <div className="text-gray-500 flex items-center gap-2">
              <span className="inline-block w-2 h-2 rounded-full bg-neon-cyan animate-pulse-glow" />
              正在连接...
            </div>
          )}
          {isStreaming && narration && (
            <span className="inline-block w-0.5 h-5 bg-neon-cyan animate-pulse ml-0.5 align-middle" />
          )}
        </div>
      )}

      {/* Token usage */}
      {usage && (
        <div className="text-sm text-gray-500 flex items-center gap-4 px-1">
          <span>
            Token 使用：input={usage.input_tokens.toLocaleString()},
            output={usage.output_tokens.toLocaleString()},
            total={usage.total_tokens.toLocaleString()}
          </span>
        </div>
      )}
    </div>
  )
}
