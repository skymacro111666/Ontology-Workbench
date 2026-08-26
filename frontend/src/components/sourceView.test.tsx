import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Envelope } from '../api/types'
import { useUiStore } from '../stores/uiStore'
import SourceView, { languageFor } from './SourceView'

/* CodeMirror 6 runs headless under jsdom (no layout needed for mount), so
   the real editor is used: assertions read the rendered .cm-line DOM. */

function ok(data: unknown) {
  return new Response(
    JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

function err(code: string, message: string, hint: string | null) {
  return new Response(
    JSON.stringify({ code, message, data: null, hint, request_id: 'r' }),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

function renderView(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const utils = render(
    <QueryClientProvider client={qc}>
      <SourceView oid="oid-1" />
    </QueryClientProvider>,
  )
  return { ...utils, qc }
}

const PAYLOAD = {
  filename: 'mini.ttl',
  format: 'turtle',
  content: '@prefix ex: <http://example.org/> .\nex:A a owl:Class .\n',
  fileHash: 'hash-1',
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useUiStore.setState({ sourceDirty: false, sourceSaveFn: null, pendingView: null })
})

describe('languageFor', () => {
  it('maps ontology formats onto editor languages, plain text otherwise', () => {
    expect(languageFor('turtle')).toBeTruthy()
    expect(languageFor('n3')).toBeTruthy()
    expect(languageFor('xml')).toBeTruthy()
    expect(languageFor('rdf+xml')).toBeTruthy()
    expect(languageFor('trix')).toBeUndefined()
  })
})

describe('SourceView', () => {
  it('fetches /source once mounted and renders the verbatim text with line numbers', async () => {
    const fetchMock = vi.fn(async (url: string | URL) => {
      expect(String(url)).toBe('/api/ontologies/oid-1/source')
      return ok(PAYLOAD)
    })
    const { container } = renderView(fetchMock)

    // Header row names the file and its format.
    expect(await screen.findByText('mini.ttl')).toBeTruthy()
    expect(screen.getByText('turtle')).toBeTruthy()
    // The editor renders every source line, verbatim (CM6 counts the
    // trailing newline as one more empty line).
    await waitFor(() => {
      const lines = [...container.querySelectorAll('.cm-line')].map((l) => l.textContent)
      expect(lines).toEqual(PAYLOAD.content.split('\n'))
    })
    // Line-number gutter is on.
    expect(container.querySelector('.cm-gutters')).toBeTruthy()
    // Line wrapping is on (long lines fold at the content cap, no h-scroll).
    expect(container.querySelector('.cm-content')?.classList.contains('cm-lineWrapping')).toBe(
      true,
    )
  })

  it('destroys the editor on unmount', async () => {
    const fetchMock = vi.fn(async () => ok(PAYLOAD))
    const { container } = renderView(fetchMock)
    await waitFor(() => expect(container.querySelector('.cm-editor')).toBeTruthy())
    cleanup()
    expect(container.querySelector('.cm-editor')).toBeNull()
  })

  it('shows the shared retry card on failure and recovers on retry', async () => {
    let fail = true
    const fetchMock = vi.fn(async () => {
      if (fail) throw new TypeError('Failed to fetch')
      return ok(PAYLOAD)
    })
    renderView(fetchMock)

    expect(await screen.findByText('加载失败')).toBeTruthy()
    fail = false
    await userEvent.click(screen.getByRole('button', { name: '重试' }))
    expect(await screen.findByText('mini.ttl')).toBeTruthy()
  })

  it('is editable and tracks dirtiness with a save affordance', async () => {
    const fetchMock = vi.fn(async () => ok(PAYLOAD))
    const { container } = renderView(fetchMock)
    await screen.findByText('mini.ttl')
    // Editable: CM content is a live editable region (no cm-readonly).
    const content = container.querySelector('.cm-content') as HTMLElement
    expect(content.getAttribute('contenteditable')).toBeTruthy()

    await userEvent.click(content)
    await userEvent.keyboard('ex:Extra a owl:Class .')
    expect(screen.getByText('● 未保存')).toBeTruthy()
    expect(screen.getByRole('button', { name: '保存' })).toBeTruthy()
  })

  it('saves via PUT with content+baseFileHash, then clears dirt', async () => {
    let putBody: { content: string; baseFileHash: string } | undefined
    const fetchMock = vi.fn(async (_url: string | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        putBody = JSON.parse(String(init.body))
        return ok({ id: 'oid-1', fileHash: 'hash-2' })
      }
      return ok(PAYLOAD)
    })
    const { container } = renderView(fetchMock)
    await screen.findByText('mini.ttl')
    const content = container.querySelector('.cm-content') as HTMLElement
    await userEvent.click(content)
    // jsdom has no layout, so the click cannot place the caret by geometry
    // (it collapses to the content start). Move it to the doc end — the
    // browser equivalent of clicking after the last character.
    document.getSelection()?.selectAllChildren(content)
    document.getSelection()?.collapseToEnd()
    await userEvent.keyboard('x')

    await userEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(putBody?.baseFileHash).toBe('hash-1'))
    expect(putBody?.content.endsWith('x')).toBe(true)
    // Dirt cleared + the invalidateQueries() refetch re-reads /source.
    await waitFor(() => expect(screen.queryByText('● 未保存')).toBeNull())
    const sourceGets = fetchMock.mock.calls.filter(
      ([u, i]) => String(u).endsWith('/source') && !i?.method,
    )
    expect(sourceGets.length).toBeGreaterThanOrEqual(2)
  })

  it('shows an inline parse error and keeps the edits', async () => {
    const fetchMock = vi.fn(async (_url: string | URL, init?: RequestInit) => {
      if (init?.method === 'PUT')
        return err('PARSE_FAILED', 'Syntax error: line 2', 'Fix the syntax and retry.')
      return ok(PAYLOAD)
    })
    const { container } = renderView(fetchMock)
    await screen.findByText('mini.ttl')
    const content = container.querySelector('.cm-content') as HTMLElement
    await userEvent.click(content)
    await userEvent.keyboard('x')
    await userEvent.click(screen.getByRole('button', { name: '保存' }))

    expect((await screen.findByRole('alert')).textContent).toContain('Syntax error: line 2')
    expect(screen.getByText(/Fix the syntax/)).toBeTruthy()
    // Edits kept: still dirty, still one character more.
    expect(screen.getByText('● 未保存')).toBeTruthy()
  })

  it('offers reload-or-continue on EDIT_CONFLICT', async () => {
    // A conflict means the server has a NEWER version — after reload the
    // editor must render it (not the stale GET payload: structural sharing
    // would keep the old data reference and skip the rebuild).
    const serverV2 = '@prefix ex: <http://example.org/> .\nex:B a owl:Class .\n'
    let reloaded = false
    const fetchMock = vi.fn(async (_url: string | URL, init?: RequestInit) => {
      if (init?.method === 'PUT')
        return err('EDIT_CONFLICT', 'The file changed since it was loaded', null)
      if (reloaded) return ok({ ...PAYLOAD, content: serverV2, fileHash: 'hash-2' })
      return ok(PAYLOAD)
    })
    const { container } = renderView(fetchMock)
    await screen.findByText('mini.ttl')
    const content = container.querySelector('.cm-content') as HTMLElement
    await userEvent.click(content)
    await userEvent.keyboard('x')
    await userEvent.click(screen.getByRole('button', { name: '保存' }))
    expect(await screen.findByRole('alertdialog')).toBeTruthy()

    // Continue editing: dialog closes, local edits survive.
    await userEvent.click(screen.getByRole('button', { name: '继续编辑' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(container.querySelector('.cm-content')?.textContent).toContain('x')

    // Reload: local edits are discarded, the server's new version is rendered.
    await userEvent.click(screen.getByRole('button', { name: '保存' }))
    await screen.findByRole('alertdialog')
    reloaded = true
    await userEvent.click(screen.getByRole('button', { name: '重新加载' }))
    await waitFor(() => {
      const lines = [...container.querySelectorAll('.cm-line')].map((l) => l.textContent)
      expect(lines).toEqual(serverV2.split('\n'))
    })
  })

  it('never clobbers local edits on a background refetch', async () => {
    // A background refetch (focus/invalidate) resolving with a NEWER server
    // version must not replace the editor doc while it has local edits.
    let generation = 0
    const fetchMock = vi.fn(async () =>
      ok(
        generation === 0
          ? PAYLOAD
          : { ...PAYLOAD, content: 'server moved on\n', fileHash: 'hash-2' },
      ),
    )
    const { container, qc } = renderView(fetchMock)
    await screen.findByText('mini.ttl')
    const content = container.querySelector('.cm-content') as HTMLElement
    await userEvent.click(content)
    await userEvent.keyboard('ex:Local a owl:Class .')
    generation = 1
    await act(async () => {
      await qc.refetchQueries({ queryKey: ['source', 'oid-1'] })
    })
    // react-query notifies observers via setTimeout(0) — yield a macrotask
    // so the fresh data actually reaches the component before asserting.
    await new Promise((r) => setTimeout(r, 10))
    const lines = [...container.querySelectorAll('.cm-line')].map((l) => l.textContent)
    expect(lines.join('\n')).toContain('ex:Local')
  })

  it('warns on beforeunload while dirty and clears store state on unmount', async () => {
    const fetchMock = vi.fn(async () => ok(PAYLOAD))
    const { container } = renderView(fetchMock)
    await screen.findByText('mini.ttl')
    const content = container.querySelector('.cm-content') as HTMLElement
    await userEvent.click(content)
    await userEvent.keyboard('x')
    expect(useUiStore.getState().sourceDirty).toBe(true)
    expect(useUiStore.getState().sourceSaveFn).toBeTruthy()

    const evt = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(evt)
    expect(evt.defaultPrevented).toBe(true)

    cleanup()
    expect(useUiStore.getState().sourceDirty).toBe(false)
    expect(useUiStore.getState().sourceSaveFn).toBeNull()
  })
})
