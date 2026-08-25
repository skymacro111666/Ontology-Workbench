import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Envelope } from '../api/types'
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
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
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
})
