import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { readFileSync } from 'fs'
import { ebmPackages, playgroundRuntime, playgroundRuntimePath } from './playgroundRuntime'

export default defineConfig(({ mode, isPreview }) => {
  // Load env vars from .env, .env.[mode], etc.
  const env = loadEnv(mode, process.cwd(), '')
  const base = env.VITE_BASE_PATH || '/'
  const apiPrefix = base.startsWith('/') ? base.replace(/\/$/, '') : ''

  // Read version from package.json so it stays in sync automatically.
  const pkg = JSON.parse(
    readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8'),
  ) as { version: string }

  return {
    // GitHub Pages serves at /<repo-name>/ — set via VITE_BASE_PATH or default to '/'
    base,

    plugins: [react(), !isPreview && mode !== 'test' && playgroundRuntime(env.VITE_STATIC_MODE === 'true')],
    worker: { format: 'es' },

    // Inject build-time constants so version numbers never go stale.
    define: {
      __APP_VERSION__: JSON.stringify(pkg.version),
      __BUILD_DATE__: JSON.stringify(new Date().toISOString().slice(0, 10)),
      __PLAYGROUND_RUNTIME_PATH__: JSON.stringify(playgroundRuntimePath),
      __EBM_PACKAGES__: JSON.stringify(ebmPackages),
    },

    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
        // Single-source colour palette shared with the Python backend.
        '@dreamulator/palettes': path.resolve(__dirname, '../src/dreamulator/map/palettes.json'),
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
      fs: {
        // Allow the frontend project root (serves index.html) plus the shared
        // palette JSON in the backend src/ tree. Specifying `allow` REPLACES
        // Vite's default scope, so the root must be listed explicitly.
        allow: [path.resolve(__dirname, '.'), path.resolve(__dirname, '../src')],
      },
      port: 5173,
      proxy: {
        [`${apiPrefix}/api`]: {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
          rewrite: url => url.slice(apiPrefix.length),
        },
      },
    },
  }
})
