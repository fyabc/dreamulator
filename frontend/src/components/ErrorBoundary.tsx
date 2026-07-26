/**
 * ErrorBoundary — catches render errors and shows a fallback UI.
 *
 * Wrap around any component that may throw (e.g. WebGL Canvases, data-heavy
 * pages) to prevent the entire app from going blank on a single crash.
 */

import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** Optional custom message shown to the user. */
  message?: string
}

interface State {
  hasError: boolean
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error) {
    console.error('[ErrorBoundary] Caught render error:', error)
  }

  handleRetry = () => {
    this.setState({ hasError: false })
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center h-full min-h-[300px]">
          <div className="glass-panel p-6 text-center max-w-sm">
            <p className="text-red-400 font-semibold mb-2">渲染错误</p>
            <p className="text-gray-400 text-sm mb-4">
              {this.props.message ?? '此组件在渲染时发生了错误。请尝试刷新页面。'}
            </p>
            <button
              onClick={this.handleRetry}
              className="px-4 py-2 text-sm rounded bg-space-surface text-gray-300 hover:text-neon-cyan border border-space-border hover:border-neon-cyan/30 transition-colors"
            >
              重试
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
