import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'
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
    // the panel's own section heading/subtitle are dropped on the page —
    // the page-level heading stands alone (page subtitle starts with 管理)
    expect(screen.queryByText('数据库连接')).toBeNull()
    expect(
      screen.queryByText('供「从数据库起草」向导选用的已存连接；密码加密存储，永不下发。'),
    ).toBeNull()
    expect(await screen.findByText('还没有已存连接')).toBeTruthy()
  })

  it('carries a back button on the title row that navigates back in history', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ok([])),
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/settings', '/db-connections']} initialIndex={1}>
          <Routes>
            <Route path="/settings" element={<span>settings-page</span>} />
            <Route path="/db-connections" element={<DbConnections />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    const back = await screen.findByRole('button', { name: '返回' })
    await userEvent.click(back)
    expect(await screen.findByText('settings-page')).toBeTruthy()
  })
})
