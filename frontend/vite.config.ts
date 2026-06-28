import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig(({ mode }) => {
  // Load env vars from .env, .env.[mode], etc.
  const env = loadEnv(mode, process.cwd(), '')

  return {
    // GitHub Pages serves at /<repo-name>/ — set via VITE_BASE_PATH or default to '/'
    base: env.VITE_BASE_PATH || '/',

    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    // Support top-level await (required by Three.js WebGPU module)
    build: {
      target: ['chrome89', 'edge89', 'firefox89', 'safari15'],
    },
    optimizeDeps: {
      esbuildOptions: {
        target: 'es2022',
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
  }
})
