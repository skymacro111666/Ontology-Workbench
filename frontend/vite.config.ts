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
    // Kept so CI stays green in checkouts stripped of test files.
    passWithNoTests: true,
  },
})
