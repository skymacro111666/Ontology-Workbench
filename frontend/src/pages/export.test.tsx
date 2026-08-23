import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { toast } from 'sonner'
import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import Export from './Export'
import type { Envelope } from '../api/types'

const OUT_DIR = '/srv/data/exports/pizza-20260823'

/** Envelope helpers matching the API contract (code/message/data/hint/request_id). */
const ok = (data: unknown) =>
  new Response(JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' }), {
    headers: { 'Content-Type': 'application/json' },
  })

const err = (code: string) =>
  new Response(
    JSON.stringify({ code, message: '目标目录非空', data: null, hint: null, request_id: 'r' } satisfies Envelope<null>),
    { headers: { 'Content-Type': 'application/json' } },
  )

/** POSTs to the export endpoint, decoded from the JSON body. */
function exportBodies(fetchMock: Mock) {
  return fetchMock.mock.calls
    .filter(([url, init]) => String(url).includes('/export/site') && init?.method === 'POST')
    .map(([, init]) => JSON.parse(String(init.body)))
}

/** jsdom ships no navigator.clipboard; install one and hand back the spy. */
function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
  return writeText
}

function renderExport(fetchMock: Mock) {
  vi.stubGlobal('fetch', fetchMock)
  render(
    <MemoryRouter initialEntries={['/export/oid-1']}>
      {/* Route params only resolve through a Routes declaration. */}
      <Routes>
        <Route path="/export/:oid" element={<Export />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  // Drop the clipboard stub so later suites see jsdom's original state.
  Reflect.deleteProperty(navigator, 'clipboard')
})

describe('Export', () => {
  it('submits outDir and the force flag in the POST body', async () => {
    const fetchMock = vi.fn(async () => ok({ outputDir: OUT_DIR, pageCount: 5 }))
    renderExport(fetchMock)

    await userEvent.type(screen.getByLabelText('输出目录（可选）'), '/tmp/my-site ')
    await userEvent.click(screen.getByRole('switch'))
    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))

    await waitFor(() => expect(exportBodies(fetchMock)).toHaveLength(1))
    expect(fetchMock).toHaveBeenCalledWith('/api/ontologies/oid-1/export/site', expect.anything())
    // Blank means default on the server; trailing space is trimmed away.
    expect(exportBodies(fetchMock)[0]).toEqual({ outDir: '/tmp/my-site', force: true })
  })

  it('renders the result card with outputDir and pageCount on success', async () => {
    const fetchMock = vi.fn(async () => ok({ outputDir: OUT_DIR, pageCount: 12 }))
    renderExport(fetchMock)

    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))

    expect(await screen.findByText(OUT_DIR)).toBeTruthy()
    expect(screen.getByText('共 12 页（1 个索引页 + 11 个实体页）')).toBeTruthy()
    // Blank input sends no outDir so the server picks the default location.
    expect(exportBodies(fetchMock)[0]).toEqual({ force: false })
  })

  it('copies the output dir through the clipboard and toasts 已复制', async () => {
    const writeText = stubClipboard()
    const toastSuccess = vi.spyOn(toast, 'success')
    const fetchMock = vi.fn(async () => ok({ outputDir: OUT_DIR, pageCount: 5 }))
    renderExport(fetchMock)

    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))
    await userEvent.click(await screen.findByRole('button', { name: '复制' }))

    expect(writeText).toHaveBeenCalledWith(OUT_DIR)
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('已复制'))
  })

  it('clears the success card when a resubmit fails', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(ok({ outputDir: OUT_DIR, pageCount: 5 }))
      .mockResolvedValueOnce(err('VALIDATION_ERROR'))
    renderExport(fetchMock)

    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))
    expect(await screen.findByText(OUT_DIR)).toBeTruthy()

    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))
    expect(await screen.findByRole('alert')).toBeTruthy()
    // The resubmit failed: the stale success card must not sit beside the alert.
    expect(screen.queryByText(OUT_DIR)).toBeNull()
    expect(screen.queryByText(/共 \d+ 页/)).toBeNull()
  })

  it('maps VALIDATION_ERROR to the directory-not-empty copy', async () => {
    const fetchMock = vi.fn(async () => err('VALIDATION_ERROR'))
    renderExport(fetchMock)

    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('目录非空，勾选覆盖或换一个')).toBeTruthy()
  })
})
