import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useParams, useSearchParams } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import CommandPalette from './CommandPalette'
import { LAST_OID_KEY } from '../auth/AuthContext'
import { useBrowseStore } from '../stores/browseStore'
import type { Envelope, SearchHit } from '../api/types'

const EID = 'http://example.org/Margherita'
const HITS: SearchHit[] = [
  { eid: EID, curie: 'pizza:Margherita', label: { zh: '玛格丽特' }, type: 'Class', matchedField: 'label' },
]

function ok(data: unknown) {
  return new Response(
    JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

/** Route target probe: surfaces where navigation landed (oid + eid param). */
function BrowseProbe() {
  const { oid = '' } = useParams()
  const [sp] = useSearchParams()
  return <div>probe:{oid}:{sp.get('eid') ?? ''}</div>
}

function renderPalette(fetchMock: Mock = vi.fn(async () => ok(HITS))) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<CommandPalette />} />
          <Route path="/browse/:oid" element={<BrowseProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return fetchMock
}

/** Open via the global shortcut; resolves to the palette input. */
async function openPalette() {
  fireEvent.keyDown(window, { key: 'k', metaKey: true })
  return screen.findByPlaceholderText('搜索类 / 属性…')
}

// Vitest globals are off, so RTL auto-cleanup never registers (appShell.test note);
// fetch stubs and localStorage likewise reset between tests.
beforeEach(() => {
  localStorage.setItem(LAST_OID_KEY, 'oid-1')
  useBrowseStore.setState({ selectedEid: null, revealEid: null })
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  localStorage.removeItem(LAST_OID_KEY)
})

describe('CommandPalette', () => {
  it('opens on ⌘K and closes on Esc', async () => {
    renderPalette()
    expect(screen.queryByRole('dialog')).toBeNull()

    expect(await openPalette()).toBeTruthy()
    expect(screen.getByRole('dialog')).toBeTruthy()
    // Shortcut hint sits at the top of the panel.
    expect(screen.getByText('Ctrl/⌘ K 打开 · Esc 关闭')).toBeTruthy()

    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('debounces typing into one /search call and lists curie + matchedField + type', async () => {
    // Fake timers make the 150ms debounce deterministic: the clock is frozen
    // while the query grows, so exactly one request can ever fire.
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    const fetchMock = renderPalette()
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    const input = screen.getByPlaceholderText('搜索类 / 属性…')

    // Keystrokes land without advancing the clock (userEvent hangs under fake
    // timers in this setup; fireEvent.change drives the same value path).
    for (const partial of ['玛', '玛格', '玛格丽', '玛格丽特']) {
      fireEvent.change(input, { target: { value: partial } })
    }
    expect(fetchMock).not.toHaveBeenCalled()

    await act(async () => {
      await vi.advanceTimersByTimeAsync(150)
    })

    // oid comes from LAST_OID_KEY when no /:oid route is active. vi.waitFor
    // keeps advancing the fake clock while react-query settles the fetch.
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/ontologies/oid-1/search?q=${encodeURIComponent('玛格丽特')}`,
        expect.anything(),
      )
    })
    // The debounce collapsed the keystrokes into a single request.
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(screen.getByText('pizza:Margherita')).toBeTruthy()
    expect(screen.getByText('label')).toBeTruthy()
    expect(screen.getByText('Class')).toBeTruthy()
  })

  it('does not flash 无匹配结果 while the search fetch is in flight', async () => {
    // Fake timers freeze the debounce; a never-resolving fetch pins the
    // query in isPending for the whole test.
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
    const fetchMock: Mock = vi.fn(() => new Promise<Response>(() => {}))
    renderPalette(fetchMock)
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    fireEvent.change(screen.getByPlaceholderText('搜索类 / 属性…'), { target: { value: '玛格丽特' } })

    await act(async () => {
      await vi.advanceTimersByTimeAsync(150)
    })
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))

    // The query dispatched but has not resolved: the empty state stays hidden.
    expect(screen.queryByText('无匹配结果')).toBeNull()
  })

  it('reports a failed search instead of 无匹配结果', async () => {
    // A rejected search must not read as "no matches" (pre-existing issue).
    const fetchMock: Mock = vi.fn(async () => {
      throw new TypeError('network down')
    })
    renderPalette(fetchMock)
    const input = await openPalette()
    await userEvent.type(input, '玛格丽特')
    await waitFor(() => expect(screen.getByText('搜索失败，请稍后重试')).toBeTruthy())
    expect(screen.queryByText('无匹配结果')).toBeNull()
  })

  it('navigates to /browse/:oid?eid=… and reveals the pick in the tree store', async () => {
    renderPalette()
    const input = await openPalette()
    await userEvent.type(input, '玛格丽特')

    await userEvent.click(await screen.findByText('pizza:Margherita'))

    expect(await screen.findByText(`probe:oid-1:${EID}`)).toBeTruthy()
    expect(useBrowseStore.getState().selectedEid).toBe(EID)
    expect(useBrowseStore.getState().revealEid).toBe(EID)
  })
})
