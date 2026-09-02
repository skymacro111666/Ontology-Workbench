import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import BlankOntologyDialog from './BlankOntologyDialog'
import { useUiStore } from '../stores/uiStore'

const ok = (data: unknown) =>
  new Response(JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' }), {
    headers: { 'Content-Type': 'application/json' },
  })

const err = (code: string, status = 409) =>
  new Response(JSON.stringify({ code, message: code, data: null, hint: null, request_id: 'r' }), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

/** Marks navigations so the /browse/:id jump is assertable. */
function Where() {
  const loc = useLocation()
  return <p>at:{loc.pathname}</p>
}

function renderDialog() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Routes>
          <Route path="/" element={<BlankOntologyDialog />} />
          <Route path="/browse/:id" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => useUiStore.getState().setBlankOpen(true))
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useUiStore.getState().setBlankOpen(false)
})

it('creates from the name and jumps into the new workspace', async () => {
  const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
    expect(String(url)).toBe('/api/ontologies/blank')
    expect(JSON.parse(String(init?.body))).toEqual({ name: 'My Domain' })
    return ok({ id: 'blank-1', title: 'My Domain', filename: 'my-domain.ttl', source: 'created' })
  })
  vi.stubGlobal('fetch', fetchMock)
  renderDialog()

  await userEvent.type(await screen.findByLabelText('名称'), 'My Domain')
  await userEvent.click(screen.getByRole('button', { name: '创建' }))
  expect(await screen.findByText('at:/browse/blank-1')).toBeTruthy()
  // The dialog closed behind the navigation.
  expect(useUiStore.getState().blankOpen).toBe(false)
})

it('keeps the dialog open with a duplicate hint on DUPLICATE_FILENAME', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => err('DUPLICATE_FILENAME')),
  )
  renderDialog()

  await userEvent.type(await screen.findByLabelText('名称'), 'dup')
  await userEvent.click(screen.getByRole('button', { name: '创建' }))
  expect(await screen.findByText(/同名本体已存在/)).toBeTruthy()
  expect(useUiStore.getState().blankOpen).toBe(true)
})

it('disables creating until a name is given', async () => {
  renderDialog()
  const create = await screen.findByRole('button', { name: '创建' })
  expect(create.getAttribute('disabled')).not.toBeNull()
})

it('sends the namespace and appends # when it lacks a trailing separator', async () => {
  const fetchMock = vi.fn(async (_url: string | URL, init?: RequestInit) => {
    expect(JSON.parse(String(init?.body))).toEqual({
      name: 'KG',
      namespace: 'https://example.org/kg#',
    })
    return ok({ id: 'blank-2', title: 'KG', filename: 'kg.ttl', source: 'created' })
  })
  vi.stubGlobal('fetch', fetchMock)
  renderDialog()

  await userEvent.type(await screen.findByLabelText('名称'), 'KG')
  await userEvent.type(screen.getByLabelText('命名空间（可选）'), 'https://example.org/kg')
  await userEvent.click(screen.getByRole('button', { name: '创建' }))
  expect(await screen.findByText('at:/browse/blank-2')).toBeTruthy()
})

it('rejects a whitespace namespace inline without sending', async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
  renderDialog()

  await userEvent.type(await screen.findByLabelText('名称'), 'X')
  await userEvent.type(screen.getByLabelText('命名空间（可选）'), 'has space')
  await userEvent.click(screen.getByRole('button', { name: '创建' }))
  expect(await screen.findByText(/命名空间不能包含空格/)).toBeTruthy()
  expect(fetchMock).not.toHaveBeenCalled()
})
