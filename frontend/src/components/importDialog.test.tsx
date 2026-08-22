import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ImportDialog from './ImportDialog'
import { useUiStore } from '../stores/uiStore'

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><ImportDialog /></QueryClientProvider>)
}

beforeEach(() => useUiStore.getState().setImportOpen(true))

// Vitest globals are off, so RTL auto-cleanup never registers — without this,
// the previous test's tree stays mounted and shares the uiStore dialog.
afterEach(() => cleanup())

it('uploads a chosen file and closes on success', async () => {
  const invalidate = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async () => new Response(
    JSON.stringify({ code: 'OK', message: 'ok', data: { id: 'o1', title: 't', prefixes: {} }, hint: null, request_id: 'r' }),
    { headers: { 'Content-Type': 'application/json' } },
  )))
  const spy = vi.spyOn(QueryClient.prototype, 'invalidateQueries').mockImplementation(invalidate)
  wrap()
  const file = new File(['@prefix ex: <http://e/> .'], 'mini.ttl', { type: 'text/turtle' })
  const input = document.querySelector('input[type=file]') as HTMLInputElement
  await userEvent.upload(input, file)
  expect(await screen.findByText(/mini\.ttl/)).toBeTruthy()
  expect(fetch).toHaveBeenCalledWith('/api/ontologies', expect.objectContaining({ method: 'POST' }))
  expect(invalidate).toHaveBeenCalled()
  spy.mockRestore()
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
