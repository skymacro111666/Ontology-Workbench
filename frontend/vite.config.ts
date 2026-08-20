import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8734' },
  },
  test: {
    // Real tests arrive with Task 14 (api client); keep CI green until then.
    passWithNoTests: true,
  },
})
