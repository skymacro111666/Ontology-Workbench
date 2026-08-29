import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import OntologySwitcher from './OntologySwitcher'
import type { Envelope, OntologySummary } from '../api/types'

function ok(data: unknown) {
  return new Response(
    JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' } satisfies Envelope<unknown>),
    { headers: { 'Content-Type': 'application/json' } },
  )
}

function summary(id: string, title: string): OntologySummary {
  return {
    id,
    title,
    filename: `${id}.ttl`,
    format: 'turtle',
    classCount: 1,
    propertyCount: 0,
    axiomCount: 2,
    instanceCount: 0,
    fileSizeBytes: 10,
    createdAt: '2026-01-01T00:00:00Z',
  } as OntologySummary
}

function draw(fetchImpl: () => Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn(fetchImpl))
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <OntologySwitcher />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('lists ontologies from the API', async () => {
  draw(async () => ok({ items: [summary('oid-1', 'Pizza')], total: 1 }))
  await userEvent.click(screen.getByRole('button', { name: /选择本体/ }))
  expect(await screen.findByText('Pizza')).toBeTruthy()
})

it('says 加载中 while the list is pending (backlog T4①)', async () => {
  draw(() => new Promise<Response>(() => {}))
  await userEvent.click(screen.getByRole('button', { name: /选择本体/ }))
  expect(await screen.findByText('加载中…')).toBeTruthy()
  expect(screen.queryByText('暂无本体')).toBeNull()
})

it('says 加载失败 on error instead of masquerading as empty (backlog T4①)', async () => {
  draw(async () => {
    throw new TypeError('network down')
  })
  await userEvent.click(screen.getByRole('button', { name: /选择本体/ }))
  expect(await screen.findByText('加载失败')).toBeTruthy()
  expect(screen.queryByText('暂无本体')).toBeNull()
})
