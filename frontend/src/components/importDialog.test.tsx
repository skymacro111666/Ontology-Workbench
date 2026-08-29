import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ImportDialog from './ImportDialog'
import { useUiStore } from '../stores/uiStore'

let invalidateSpy: ReturnType<typeof vi.spyOn> | null = null

/* Uploads go through XMLHttpRequest (fetch cannot report upload progress).
   This fake records instances so tests can drive onprogress/onload by hand. */
const xhrInstances: FakeXHR[] = []
class FakeXHR {
  upload = { onprogress: null as ((e: { loaded: number; total: number }) => void) | null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  status = 200
  responseText = ''
  opened: [string, string] | null = null
  sent = false
  open(method: string, url: string) {
    this.opened = [method, url]
  }
  setRequestHeader() {}
  send() {
    this.sent = true
    xhrInstances.push(this)
  }
}
function stubXHR() {
  xhrInstances.length = 0
  vi.stubGlobal('XMLHttpRequest', FakeXHR)
}
const OK_ENV = JSON.stringify({
  code: 'OK',
  message: 'ok',
  data: { id: 'o1', title: 't', prefixes: {} },
  hint: null,
  request_id: 'r',
})

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
  stubXHR()
  const invalidate = vi.fn()
  const spy = vi.spyOn(QueryClient.prototype, 'invalidateQueries').mockImplementation(invalidate)
  invalidateSpy = spy
  wrap()
  const file = new File(['@prefix ex: <http://e/> .'], 'mini.ttl', { type: 'text/turtle' })
  const input = document.querySelector('input[type=file]') as HTMLInputElement
  await userEvent.upload(input, file)
  const xhr = xhrInstances.at(-1)!
  expect(xhr.opened).toEqual(['POST', '/api/ontologies'])
  xhr.responseText = OK_ENV
  await act(async () => {
    xhr.onload?.()
  })
  expect(await screen.findByText(/mini\.ttl/)).toBeTruthy()
  expect(invalidate).toHaveBeenCalled()
})

it('shows upload progress, then the parsing phase, then succeeds', async () => {
  stubXHR()
  const invalidate = vi.fn()
  const spy = vi.spyOn(QueryClient.prototype, 'invalidateQueries').mockImplementation(invalidate)
  invalidateSpy = spy
  wrap()
  const input = document.querySelector('input[type=file]') as HTMLInputElement
  await userEvent.upload(input, new File([new Uint8Array(200)], 'go.owl'))
  const xhr = xhrInstances.at(-1)!
  await act(async () => {
    xhr.upload.onprogress?.({ loaded: 100, total: 200 })
  })
  const bar = screen.getByRole('progressbar') as HTMLElement
  expect(bar.getAttribute('aria-valuenow')).toBe('50')
  expect(await screen.findByText(/50%/)).toBeTruthy()
  await act(async () => {
    xhr.upload.onprogress?.({ loaded: 200, total: 200 })
  })
  expect(await screen.findByText(/解析中/)).toBeTruthy()
  xhr.responseText = OK_ENV
  await act(async () => {
    xhr.onload?.()
  })
  await waitFor(() => expect(invalidate).toHaveBeenCalled())
})

it('re-enables the file input when the dialog reopens mid-upload', async () => {
  // Upload hangs (onload never fires); the user closes and reopens the
  // dialog — the fresh session must not inherit the stale uploading state.
  stubXHR()
  wrap()
  const input = document.querySelector('input[type=file]') as HTMLInputElement
  await userEvent.upload(input, new File(['x'], 'a.ttl'))
  const xhr = xhrInstances.at(-1)!
  expect(xhr.sent).toBe(true)
  await waitFor(() => expect(input.disabled).toBe(true))
  act(() => useUiStore.getState().setImportOpen(false))
  act(() => useUiStore.getState().setImportOpen(true))
  const fresh = document.querySelector('input[type=file]') as HTMLInputElement
  expect(fresh.disabled).toBe(false)
})

it('rejects files over 150MB before uploading', async () => {
  stubXHR()
  wrap()
  const big = new File([new Uint8Array(10)], 'huge.ttl')
  Object.defineProperty(big, 'size', { value: 151 * 1024 * 1024 })
  const input = document.querySelector('input[type=file]') as HTMLInputElement
  await userEvent.upload(input, big)
  expect(await screen.findByText(/超过 150MB/)).toBeTruthy()
  expect(xhrInstances).toHaveLength(0)
})

it('clears the size error when the dialog reopens', async () => {
  stubXHR()
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
