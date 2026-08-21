import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8734' },
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
