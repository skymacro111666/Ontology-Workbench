import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import DbConnections from './DbConnections'

/* The standalone database-connections page (user menu → 数据库设置): a page
   heading over the ConnectionsPanel, which carries the real interactions
   (covered in connectionsPanel.test.tsx). */

const ok = (data: unknown) =>
  new Response(JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' }), {
    headers: { 'Content-Type': 'application/json' },
  })

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('DbConnections page', () => {
  it('renders the page heading over the panel empty state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (String(url).includes('/db-connections/engines'))
          return ok([{ dbType: 'sqlite', label: 'SQLite', installed: true, defaultPort: null }])
        return ok([])
      }),
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <DbConnections />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.getByRole('heading', { level: 1, name: '数据库设置' })).toBeTruthy()
    expect(await screen.findByText('还没有已存连接')).toBeTruthy()
  })
})
