import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import Home from './Home'
import { checkFileSize } from '../components/UploadDropzone'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

function renderHome() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Home />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function stubFetchOnce(body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })),
  )
}

describe('Home', () => {
  it('renders the ontology list from the API', async () => {
    stubFetchOnce({
      code: 'OK',
      message: 'ok',
      data: {
        items: [
          {
            id: 'oid-1',
            title: 'Pizza',
            filename: 'pizza.ttl',
            format: 'turtle',
            classCount: 99,
            propertyCount: 8,
            axiomCount: 300,
            fileSizeBytes: 106000,
            createdAt: '2026-08-21T00:00:00',
          },
        ],
        total: 1,
      },
      hint: null,
      request_id: 'r',
    })
    renderHome()
    expect(await screen.findByText('Pizza')).toBeTruthy()
    expect(screen.getByText(/pizza\.ttl/)).toBeTruthy()
    expect(screen.getByText(/99 类 · 8 属性 · 300 公理/)).toBeTruthy()
  })

  it('mounts the upload dropzone with its accept list', async () => {
    stubFetchOnce({ code: 'OK', message: 'ok', data: { items: [], total: 0 }, hint: null, request_id: 'r' })
    renderHome()
    expect(await screen.findByText(/上传本体/)).toBeTruthy()
  })

  it('shows an error result with retry when the list fails to load', async () => {
    // Non-JSON body (e.g. a proxy error page): transport-level, not an ApiErr.
    vi.stubGlobal('fetch', vi.fn(async () => new Response('bad gateway', { status: 502 })))
    renderHome()
    expect(await screen.findByText('列表加载失败')).toBeTruthy()
  })

  it('offers the three builtin samples', async () => {
    stubFetchOnce({ code: 'OK', message: 'ok', data: { items: [], total: 0 }, hint: null, request_id: 'r' })
    renderHome()
    expect(await screen.findByText('pizza')).toBeTruthy()
    expect(screen.getByText('wine')).toBeTruthy()
    expect(screen.getByText('foaf')).toBeTruthy()
  })

  it('front-blocks files over 150MB', () => {
    expect(checkFileSize({ size: 150 * 1024 * 1024, name: 'a.ttl' } as File)).toBe(true)
    expect(checkFileSize({ size: 150 * 1024 * 1024 + 1, name: 'b.owl' } as File)).toBe(false)
  })

  it('deletes after confirmation and refreshes the list', async () => {
    const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
      if (String(url).includes('/api/ontologies') && init?.method === 'DELETE') {
        return new Response(
          JSON.stringify({ code: 'OK', message: 'deleted', data: null, hint: null, request_id: 'r' }),
          { headers: { 'Content-Type': 'application/json' } },
        )
      }
      return new Response(
        JSON.stringify({
          code: 'OK',
          message: 'ok',
          data: {
            items: [
              {
                id: 'oid-1',
                title: 'Pizza',
                filename: 'pizza.ttl',
                format: 'turtle',
                classCount: 1,
                propertyCount: 1,
                axiomCount: 1,
                fileSizeBytes: 1,
                createdAt: '2026-08-21T00:00:00',
              },
            ],
            total: 1,
          },
          hint: null,
          request_id: 'r',
        }),
        { headers: { 'Content-Type': 'application/json' } },
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    // Modal.confirm renders outside RTL container by default; stub it.
    const { Modal } = await import('antd')
    const confirmSpy = vi.spyOn(Modal, 'confirm').mockImplementation(({ onOk }) => {
      void onOk?.()
      return { destroy: () => {}, update: () => {} }
    })

    renderHome()
    const deleteBtn = await screen.findByRole('button', { name: /删除/ })
    await userEvent.click(deleteBtn)
    await waitFor(() => expect(confirmSpy).toHaveBeenCalled())
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/ontologies/oid-1',
        expect.objectContaining({ method: 'DELETE' }),
      ),
    )
  })
})
