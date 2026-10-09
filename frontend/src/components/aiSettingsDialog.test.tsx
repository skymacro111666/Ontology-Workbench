import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AiSettingsDialog from './AiSettingsDialog'
import { useUiStore } from '../stores/uiStore'

/** Envelope helpers matching the API contract (code/message/data/hint/request_id). */
const ok = (data: unknown) =>
  new Response(JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' }), {
    headers: { 'Content-Type': 'application/json' },
  })

const SETTINGS = {
  provider: 'openai',
  baseUrl: 'https://oneapi.example.com/v1',
  model: 'gpt-test',
  hasKey: true,
  keyLast4: 'ab12',
  source: 'env',
}

/** GET/PUT settings + POST test mock; PUT bodies captured for assertions. */
function settingsMock(over: Record<string, unknown> = {}, test: Record<string, unknown> = { ok: true, latencyMs: 143, reply: 'pong' }) {
  const puts: unknown[] = []
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    if (u.includes('/ai/settings') && init?.method === 'PUT') {
      puts.push(JSON.parse(String(init.body)))
      return ok(null)
    }
    if (u.includes('/ai/settings')) return ok({ ...SETTINGS, ...over })
    if (u.includes('/ai/test')) return ok(test)
    return ok(null)
  })
  return { fetchMock, puts }
}

function renderDialog() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <AiSettingsDialog />
    </QueryClientProvider>,
  )
}

/** Drive to the populated form (settings fetched into the inputs). */
async function loaded() {
  renderDialog()
  await screen.findByDisplayValue('gpt-test')
}

beforeEach(() => {
  useUiStore.getState().setAiSettingsOpen(true)
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useUiStore.getState().setAiSettingsOpen(false)
})

describe('AiSettingsDialog', () => {
  it('renders from the store flag with settings populated and the masked key hint', async () => {
    const { fetchMock } = settingsMock()
    vi.stubGlobal('fetch', fetchMock)
    await loaded()

    expect((screen.getByLabelText('提供方') as HTMLSelectElement).value).toBe('openai')
    expect((screen.getByLabelText('Base URL') as HTMLInputElement).value).toBe(
      'https://oneapi.example.com/v1',
    )
    // write-only key: only a masked placeholder, never a value
    expect(screen.getByPlaceholderText('••••ab12')).toBeTruthy()
    expect((screen.getByLabelText('API Key') as HTMLInputElement).value).toBe('')
    // source line: env
    expect(screen.getByText('环境变量')).toBeTruthy()
  })

  it('saves via PUT without apiKey when untouched, and with it when typed', async () => {
    const { fetchMock, puts } = settingsMock()
    vi.stubGlobal('fetch', fetchMock)
    await loaded()

    await userEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0]).not.toHaveProperty('apiKey')
    expect(puts[0]).toEqual({
      provider: 'openai',
      baseUrl: 'https://oneapi.example.com/v1',
      model: 'gpt-test',
    })

    await userEvent.type(screen.getByLabelText('API Key'), 'sk-fresh')
    await userEvent.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(puts).toHaveLength(2))
    expect(puts[1]).toEqual({
      provider: 'openai',
      baseUrl: 'https://oneapi.example.com/v1',
      model: 'gpt-test',
      apiKey: 'sk-fresh',
    })
  })

  it('测试连接 shows the probe latency and a failure shows the message', async () => {
    const okMock = settingsMock()
    vi.stubGlobal('fetch', okMock.fetchMock)
    await loaded()

    await userEvent.click(screen.getByRole('button', { name: '测试连接' }))
    expect(await screen.findByText('连接正常 · 143ms')).toBeTruthy()
    vi.unstubAllGlobals()

    const failMock = settingsMock({}, { ok: false, message: 'upstream 401' })
    vi.stubGlobal('fetch', failMock.fetchMock)
    await userEvent.click(screen.getByRole('button', { name: '测试连接' }))
    expect(await screen.findByText('连接失败')).toBeTruthy()
    expect(screen.getByText('upstream 401')).toBeTruthy()
  })

  it('labels the source as user settings when the row lives in the db', async () => {
    const { fetchMock } = settingsMock({ source: 'db', provider: 'anthropic' })
    vi.stubGlobal('fetch', fetchMock)
    await loaded()

    expect(screen.getByText('用户设置')).toBeTruthy()
    expect((screen.getByLabelText('提供方') as HTMLSelectElement).value).toBe('anthropic')
  })
})
