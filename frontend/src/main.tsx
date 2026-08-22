import '@fontsource/manrope/400.css'
import '@fontsource/manrope/600.css'
import '@fontsource/fira-code/400.css'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider, theme } from 'antd'
import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import App from './App'
import { Toaster } from './components/ui/sonner'
import { useSystemTheme } from './hooks/useSystemTheme'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

/** Applies app-wide providers; dark mode follows the OS via useSystemTheme. */
function Root() {
  const dark = useSystemTheme()
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        theme={{
          algorithm: dark ? theme.darkAlgorithm : theme.defaultAlgorithm,
          token: {
            colorPrimary: '#0D9488',
            borderRadius: 6,
            fontFamily: 'Manrope, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
            fontFamilyCode: '"Fira Code", ui-monospace, monospace',
          },
        }}
      >
        <BrowserRouter>
          <App />
        </BrowserRouter>
        <Toaster />
      </ConfigProvider>
    </QueryClientProvider>
  )
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
