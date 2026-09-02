import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { toast } from 'sonner'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import ExportDialog from './ExportDialog'
import { LAST_OID_KEY, TOKEN_KEY } from '../auth/AuthContext'
import { useUiStore } from '../stores/uiStore'
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

function renderDialog() {
  return render(<ExportDialog />)
}

beforeEach(() => {
  localStorage.setItem(LAST_OID_KEY, 'oid-1')
  useUiStore.getState().setExportOpen(true)
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  useUiStore.getState().setExportOpen(false)
  localStorage.removeItem(LAST_OID_KEY)
  // Drop the clipboard stub so later suites see jsdom's original state.
  Reflect.deleteProperty(navigator, 'clipboard')
  Reflect.deleteProperty(document, 'execCommand')
})

describe('ExportDialog', () => {
  it('submits outDir and the force flag in the POST body for the last ontology', async () => {
    const fetchMock = vi.fn(async () => ok({ outputDir: OUT_DIR, pageCount: 5 }))
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    await userEvent.type(await screen.findByLabelText('输出目录（可选）'), '/tmp/my-site ')
    await userEvent.click(screen.getByRole('switch'))
    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))

    await waitFor(() => expect(exportBodies(fetchMock)).toHaveLength(1))
    expect(fetchMock).toHaveBeenCalledWith('/api/ontologies/oid-1/export/site', expect.anything())
    // Blank means default on the server; trailing space is trimmed away.
    expect(exportBodies(fetchMock)[0]).toEqual({ outDir: '/tmp/my-site', force: true })
  })

  it('renders the result inside the dialog with outputDir and pageCount on success', async () => {
    const fetchMock = vi.fn(async () => ok({ outputDir: OUT_DIR, pageCount: 12 }))
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))

    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(OUT_DIR)).toBeTruthy()
    expect(within(dialog).getByText('共 12 页（1 个索引页 + 11 个实体页）')).toBeTruthy()
    // Blank input sends no outDir so the server picks the default location.
    expect(exportBodies(fetchMock)[0]).toEqual({ force: false })
    // Success keeps the dialog open: the result (path + download) lives in it.
    expect(useUiStore.getState().exportOpen).toBe(true)
  })

  it('shows the busy state on the submit button while exporting', async () => {
    let release: (value: Response) => void = () => {}
    const gate = new Promise<Response>((resolve) => {
      release = resolve
    })
    const fetchMock = vi.fn(async () => gate)
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))
    const busy = (await screen.findByRole('button', { name: '导出中…' })) as HTMLButtonElement
    expect(busy.disabled).toBe(true)

    release(ok({ outputDir: OUT_DIR, pageCount: 5 }))
    expect(await screen.findByText(OUT_DIR)).toBeTruthy()
    expect(screen.queryByRole('button', { name: '导出中…' })).toBeNull()
  })

  it('copies the output dir through the clipboard and toasts 已复制', async () => {
    const writeText = stubClipboard()
    const toastSuccess = vi.spyOn(toast, 'success')
    const fetchMock = vi.fn(async () => ok({ outputDir: OUT_DIR, pageCount: 5 }))
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))
    await userEvent.click(await screen.findByRole('button', { name: '复制' }))

    expect(writeText).toHaveBeenCalledWith(OUT_DIR)
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('已复制'))
  })

  it('falls back to execCommand when the clipboard API is unavailable', async () => {
    // No stubClipboard(): jsdom's bare navigator mirrors a non-secure
    // context (the app served over plain http on a LAN address), where
    // navigator.clipboard does not exist at all — the legacy execCommand
    // path must take over or the copy button is dead in that deployment.
    const execMock = vi.fn(() => true)
    Object.defineProperty(document, 'execCommand', { value: execMock, configurable: true })
    const toastSuccess = vi.spyOn(toast, 'success')
    const fetchMock = vi.fn(async () => ok({ outputDir: OUT_DIR, pageCount: 5 }))
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))
    await userEvent.click(await screen.findByRole('button', { name: '复制' }))

    await waitFor(() => expect(execMock).toHaveBeenCalledWith('copy'))
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith('已复制'))
  })

  it('downloads the exported site as a zip from the result card', async () => {
    localStorage.setItem(TOKEN_KEY, 'tok')
    const fetchMock = vi.fn(async (url: string | URL) => {
      if (String(url).includes('/export/site/archive')) {
        // String body: undici's Response (vitest's global) cannot consume a
        // jsdom Blob — res.blob() would hang; the browser never hits this.
        return new Response('PK-zip-bytes', {
          headers: {
            'Content-Type': 'application/zip',
            'Content-Disposition': 'attachment; filename="mini-docs-site.zip"',
          },
        })
      }
      return ok({ outputDir: OUT_DIR, pageCount: 5 })
    })
    // jsdom lacks both object-URL helpers; the anchors' clicks are spied
    // so no navigation actually happens.
    const createObjectURL = vi.fn(() => 'blob:mock')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { value: createObjectURL, configurable: true })
    Object.defineProperty(URL, 'revokeObjectURL', { value: revokeObjectURL, configurable: true })
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click')
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))
    await userEvent.click(await screen.findByRole('button', { name: '下载 zip' }))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `/api/ontologies/oid-1/export/site/archive?dir_path=${encodeURIComponent(OUT_DIR)}`,
        // Binary download still carries the bearer header.
        expect.objectContaining({ headers: { Authorization: 'Bearer tok' } }),
      ),
    )
    await waitFor(() => expect(clickSpy).toHaveBeenCalled())
    expect(createObjectURL).toHaveBeenCalled()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock')
  })

  it('clears the success card when a resubmit fails', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(ok({ outputDir: OUT_DIR, pageCount: 5 }))
      .mockResolvedValueOnce(err('VALIDATION_ERROR'))
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

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
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('目录非空，勾选覆盖或换一个')).toBeTruthy()
  })

  it('resets the previous result when the dialog reopens', async () => {
    const fetchMock = vi.fn(async () => ok({ outputDir: OUT_DIR, pageCount: 5 }))
    vi.stubGlobal('fetch', fetchMock)
    renderDialog()

    await userEvent.click(screen.getByRole('button', { name: '开始导出' }))
    expect(await screen.findByText(OUT_DIR)).toBeTruthy()

    // Radix handles Escape as the user-side close path.
    await userEvent.keyboard('{Escape}')
    useUiStore.getState().setExportOpen(true)
    expect(await screen.findByLabelText('输出目录（可选）')).toBeTruthy()
    // A fresh open must not resurrect the previous export's result.
    expect(screen.queryByText(OUT_DIR)).toBeNull()
    expect(screen.queryByRole('button', { name: '下载 zip' })).toBeNull()
  })
})
