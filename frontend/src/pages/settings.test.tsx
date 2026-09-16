import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import Settings from './Settings'

/* The agent-token settings page (MCP v1, D12): the listing carries only
   the display prefix — hashes never cross the wire; the create response's
   plaintext appears exactly once (copy + close discards it for good);
   revoking goes through window.confirm and refreshes the list at once. */

const ENVELOPE = (data: unknown) =>
  new Response(
    JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' }),
    { headers: { 'Content-Type': 'application/json' } },
  )

const ROW = {
  id: 'u1',
  label: 'claude',
  tokenPrefix: 'owag_abc',
  createdAt: '2026-09-15T00:00:00Z',
  lastUsedAt: null,
}

function renderPage(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Settings / agent tokens', () => {
  it('lists tokens with the display prefix only', async () => {
    const fetchMock = vi.fn(async () => ENVELOPE([ROW]))
    renderPage(fetchMock)
    expect(await screen.findByText('claude')).toBeTruthy()
    // The prefix renders with the truncation ellipsis the UI appends.
    expect(screen.getByText('owag_abc…')).toBeTruthy()
    expect(screen.getByText('从未')).toBeTruthy()
    // No request ever mentions the hash column.
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain('token_hash')
  })

  it('create flow shows the plaintext exactly once with a warning', async () => {
    const fetchMock = vi.fn(async (_url: string | URL, init?: RequestInit) => {
      if (init?.method === 'POST') return ENVELOPE({ label: 'ci', token: 'owag_secret' })
      return ENVELOPE([])
    })
    renderPage(fetchMock)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: '创建令牌' }))
    await user.type(screen.getByLabelText('标签'), 'ci')
    await user.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByDisplayValue('owag_secret')).toBeTruthy()
    expect(screen.getByText(/仅此一次展示/)).toBeTruthy()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/agent-tokens',
      expect.objectContaining({ method: 'POST' }),
    )
    // Closing the one-time block clears the plaintext — it cannot return.
    await user.click(screen.getByRole('button', { name: '关闭' }))
    expect(screen.queryByDisplayValue('owag_secret')).toBeNull()
  })

  it('revoke asks for confirmation, then DELETEs and refreshes the list', async () => {
    const fetchMock = vi.fn(async (_url: string | URL, init?: RequestInit) => {
      if (init?.method === 'DELETE') return ENVELOPE(null)
      return ENVELOPE([ROW])
    })
    renderPage(fetchMock)
    // jsdom does not implement window.confirm; the spy stands in for the
    // native dialog (the AlertDialog upgrade is deliberately deferred).
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '吊销' }))
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('吊销这枚令牌？'))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/agent-tokens/u1',
        expect.objectContaining({ method: 'DELETE' }),
      ),
    )
    // Revocation is immediate: the invalidated list query refetches.
    await waitFor(() => {
      const lists = fetchMock.mock.calls.filter((c) => c[0] === '/api/v1/agent-tokens')
      expect(lists).toHaveLength(2)
    })
  })

  it('declining the confirmation sends no DELETE', async () => {
    const fetchMock = vi.fn<(url: string | URL, init?: RequestInit) => Promise<Response>>(
      async () => ENVELOPE([ROW]),
    )
    renderPage(fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: '吊销' }))
    const deletes = fetchMock.mock.calls.filter((c) => c[1]?.method === 'DELETE')
    expect(deletes).toHaveLength(0)
  })
})
