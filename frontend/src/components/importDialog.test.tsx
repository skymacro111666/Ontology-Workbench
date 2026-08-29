import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ImportDialog from './ImportDialog'
import { useUiStore } from '../stores/uiStore'

let invalidateSpy: ReturnType<typeof vi.spyOn> | null = null

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><ImportDialog /></QueryClientProvider>)
}

beforeEach(() => useUiStore.getState().setImportOpen(true))

// Vitest globals are off, so RTL auto-cleanup never registers — without this,
// the previous test's tree stays mounted and shares the uiStore dialog.
// unstubAllGlobals drops each test's fetch stub so jsdom's real fetch returns;
// it does not touch vi.spyOn, so restore that explicitly (assertion failures
// must not leak a mocked QueryClient into later files).
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  invalidateSpy?.mockRestore()
  invalidateSpy = null
  localStorage.clear()
})

it('uploads a chosen file and closes on success', async () => {
  const invalidate = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async () => new Response(
    JSON.stringify({ code: 'OK', message: 'ok', data: { id: 'o1', title: 't', prefixes: {} }, hint: null, request_id: 'r' }),
    { headers: { 'Content-Type': 'application/json' } },
  )))
  const spy = vi.spyOn(QueryClient.prototype, 'invalidateQueries').mockImplementation(invalidate)
  invalidateSpy = spy
  wrap()
  const file = new File(['@prefix ex: <http://e/> .'], 'mini.ttl', { type: 'text/turtle' })
  const input = document.querySelector('input[type=file]') as HTMLInputElement
  await userEvent.upload(input, file)
  expect(await screen.findByText(/mini\.ttl/)).toBeTruthy()
  expect(fetch).toHaveBeenCalledWith('/api/ontologies', expect.objectContaining({ method: 'POST' }))
  expect(invalidate).toHaveBeenCalled()
})

it('re-enables the file input when the dialog reopens mid-upload', async () => {
  // Upload hangs; the user closes and reopens the dialog — the fresh session
  // must not inherit the stale uploading state (backlog T3rr).
  let resolveUpload!: (v: Response) => void
  vi.stubGlobal(
    'fetch',
    vi.fn(
      () =>
        new Promise<Response>((r) => {
          resolveUpload = r
        }),
    ),
  )
  wrap()
  const input = document.querySelector('input[type=file]') as HTMLInputElement
  await userEvent.upload(input, new File(['x'], 'a.ttl'))
  await waitFor(() => expect(input.disabled).toBe(true))
  act(() => useUiStore.getState().setImportOpen(false))
  act(() => useUiStore.getState().setImportOpen(true))
  const fresh = document.querySelector('input[type=file]') as HTMLInputElement
  expect(fresh.disabled).toBe(false)
  // Settle the stale promise so cleanup has no pending state.
  await act(async () => {
    resolveUpload(
      new Response(JSON.stringify({ code: 'OK', message: 'ok', data: {}, hint: null, request_id: 'r' }), {
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })
})

it('rejects files over 150MB before uploading', async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  wrap()
  const big = new File([new Uint8Array(10)], 'huge.ttl')
  Object.defineProperty(big, 'size', { value: 151 * 1024 * 1024 })
  const input = document.querySelector('input[type=file]') as HTMLInputElement
  await userEvent.upload(input, big)
  expect(await screen.findByText(/超过 150MB/)).toBeTruthy()
  expect(fetchMock).not.toHaveBeenCalled()
})

it('clears the size error when the dialog reopens', async () => {
  vi.stubGlobal('fetch', vi.fn())
  wrap()
  const big = new File([new Uint8Array(10)], 'huge.ttl')
  Object.defineProperty(big, 'size', { value: 151 * 1024 * 1024 })
  const input = document.querySelector('input[type=file]') as HTMLInputElement
  await userEvent.upload(input, big)
  expect(await screen.findByText(/超过 150MB/)).toBeTruthy()
  act(() => useUiStore.getState().setImportOpen(false))
  act(() => useUiStore.getState().setImportOpen(true))
  expect(screen.queryByText(/超过 150MB/)).toBeNull()
})
