import { cleanup, render, screen, waitFor } from '@testing-library/react'
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

function renderView(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <SourceView oid="oid-1" />
    </QueryClientProvider>,
  )
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
})
