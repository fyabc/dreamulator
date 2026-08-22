import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App.tsx'
import './i18n' // side-effect: initialises i18next before first render
import './index.css'
import { initPerfObserver, mark } from './utils/perf'

initPerfObserver()
mark('first-paint-start')

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes — data considered fresh
      gcTime: 1000 * 60,        // 1 minute — release inactive data quickly
                                 // (maps hold ~200+ MB; default 5 min would
                                 //  accumulate >600 MB after browsing 3 worlds)
      retry: 1,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)
