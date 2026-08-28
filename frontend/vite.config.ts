import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            // React runtime in its own chunk: the entry stays under the
            // 500kB warning line, and the stable name caches across deploys.
            {
              name: 'react',
              test: /[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/,
              priority: 20,
            },
            // G6's stack splits by subpackage family — render core, graph
            // kit, layout engine — so no single chunk crosses 500kB while
            // staying at three files instead of maxSize's shrapnel.
            {
              name: 'g-canvas',
              test: /[\\/]node_modules[\\/]@antv[\\/](g-canvas|g-math|g-plugin-[^\\/]+)[\\/]/,
              priority: 14,
            },
            {
              name: 'g-core',
              test: /[\\/]node_modules[\\/]@antv[\\/](g|g-lite)[\\/]/,
              priority: 12,
            },
            {
              name: 'graph-layout',
              test: /[\\/]node_modules[\\/](@antv[\\/]layout|d3-|dagre)[\\/]/,
              priority: 12,
            },
            // @antv/g6 is one barrel package; split its extension registry
            // (elements/behaviors/plugins/layouts) from the runtime core.
            {
              name: 'g6-x',
              test: /[\\/]@antv[\\/]g6[\\/].*(elements|behaviors|plugins|layouts)[\\/]/,
              priority: 12,
            },
            {
              name: 'g6',
              test: /[\\/]node_modules[\\/]@antv[\\/]g6[\\/]/,
              priority: 10,
            },
            {
              name: 'g6-kit',
              test: /[\\/]node_modules[\\/]@antv[\\/](component|util|event-emitter|expr|scale|vendor|algorithm|graphlib|hierarchy)[\\/]/,
              priority: 10,
            },
          ],
        },
      },
    },
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8734' },
    host: '0.0.0.0'
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['src/test/setup.ts'],
    // jsdom is heavy in constrained environments, so files run sequentially.
    // The `threads` pool runs them inside one reused worker thread
    // (fileParallelism: false pins maxWorkers to 1 — Vitest 4 removed
    // poolOptions.threads.singleThread in favor of this). The previous `forks`
    // pool tore down a process per file, and react-dom's queued setImmediate
    // could fire after jsdom teardown, failing otherwise-green runs with an
    // unhandled ReferenceError.
    pool: 'threads',
    fileParallelism: false,
    testTimeout: 20000,
    // Kept so CI stays green in checkouts stripped of test files.
    passWithNoTests: true,
  },
})
