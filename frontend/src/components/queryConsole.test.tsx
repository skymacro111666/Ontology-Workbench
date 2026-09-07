import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Envelope, QueryResult } from '../api/types'
import QueryConsole from './QueryConsole'

/* The 查询 view (M1): editor posts {qs} to POST /query and renders the
   three result forms; engine rejects (QUERY_INVALID) land inline. */

function env(data: unknown) {
  return new Response(
    JSON.stringify(
      { code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>,
    ),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

function errEnv(code: string, message: string, hint: string | null) {
  return new Response(
    JSON.stringify({ code, message, data: null, hint, request_id: 'r' }),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

const SELECT: QueryResult = {
  kind: 'select',
  columns: ['d', 'l'],
  rows: [
    {
      d: { type: 'iri', value: 'http://example.org/Dog', curie: 'ex:Dog' },
      l: { type: 'literal', value: 'Dog', language: 'en' },
    },
    {
      d: { type: 'iri', value: 'http://example.org/Animal', curie: 'ex:Animal' },
      l: null,
    },
  ],
  rowCount: 2,
  truncated: false,
  elapsedMs: 3.2,
}

let posted: { url: string; body: { qs: string } } | undefined

function stubFetch(result: () => Response = () => env(SELECT)) {
  return vi.fn(async (url: string | URL, init?: RequestInit) => {
    const u = String(url)
    if (u.endsWith('/query')) {
      posted = { url: u, body: JSON.parse(String(init?.body)) }
      return result()
    }
    throw new Error(`unexpected fetch: ${u}`)
  })
}

function renderConsole(fetchMock: ReturnType<typeof stubFetch>) {
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <QueryConsole oid="oid-1" />
    </QueryClientProvider>,
  )
}

describe('QueryConsole', () => {
  // No auto-cleanup in this setup: unmount + drop the fetch stub or the
  // next test finds two consoles (two 执行 buttons) in the shared document.
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('posts the edited query and renders the SELECT table', async () => {
    renderConsole(stubFetch())
    await userEvent.click(screen.getByRole('button', { name: /^执行/ }))
    // Request shape: POST /query with the editor's doc as qs.
    expect(posted?.url).toContain('/api/ontologies/oid-1/query')
    expect(posted?.body.qs).toContain('SELECT ?class ?label')
    // Table: header per column, curie-shortened IRIs, unbound cell as —.
    expect(await screen.findByText('ex:Dog')).toBeTruthy()
    expect(screen.getByText('Dog')).toBeTruthy()
    expect(screen.getByText('ex:Animal')).toBeTruthy()
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1)
    // Meta row reads the payload's numbers.
    expect(screen.getByText('2 行')).toBeTruthy()
    expect(screen.getByText('3.2 ms')).toBeTruthy()
  })

  it('renders ASK as a boolean verdict', async () => {
    renderConsole(
      stubFetch(() => env({ kind: 'ask', boolean: true, elapsedMs: 1 } satisfies QueryResult)),
    )
    await userEvent.click(screen.getByRole('button', { name: /^执行/ }))
    expect(await screen.findByText('真')).toBeTruthy()
  })

  it('renders CONSTRUCT as turtle text', async () => {
    renderConsole(
      stubFetch(
        () =>
          env({
            kind: 'construct',
            tripleCount: 1,
            turtle: '<http://x/a> <http://x/b> <http://x/c> .',
            truncated: false,
            elapsedMs: 2,
          } satisfies QueryResult),
      ),
    )
    await userEvent.click(screen.getByRole('button', { name: /^执行/ }))
    expect(
      await screen.findByText('<http://x/a> <http://x/b> <http://x/c> .'),
    ).toBeTruthy()
  })

  it('shows zero rows quietly', async () => {
    renderConsole(
      stubFetch(() =>
        env({ ...SELECT, rows: [], rowCount: 0 } satisfies QueryResult),
      ),
    )
    await userEvent.click(screen.getByRole('button', { name: /^执行/ }))
    expect(await screen.findByText('查询返回 0 行')).toBeTruthy()
  })

  it('renders engine rejections inline with the parse hint', async () => {
    renderConsole(
      stubFetch(() => errEnv('QUERY_INVALID', 'The query is not valid read-only SPARQL', 'error at 1:1')),
    )
    await userEvent.click(screen.getByRole('button', { name: /^执行/ }))
    expect(await screen.findByText('查询失败')).toBeTruthy()
    expect(screen.getByText(/error at 1:1/)).toBeTruthy()
  })

  it('loading a sample rewrites the editor doc', async () => {
    renderConsole(stubFetch())
    await userEvent.selectOptions(
      screen.getByLabelText('示例查询'),
      screen.getByRole('option', { name: '没有 rdfs:label 的类' }),
    )
    const doc = document.querySelector('.cm-content')?.textContent ?? ''
    expect(doc).toContain('FILTER NOT EXISTS')
  })
})
