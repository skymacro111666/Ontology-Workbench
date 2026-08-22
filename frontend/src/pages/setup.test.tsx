import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'
import Setup from './Setup'
import { AuthProvider } from '../auth/AuthContext'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

/** Envelope helpers matching the API contract (code/message/data/hint/request_id). */
const ok = (data: unknown) =>
  new Response(JSON.stringify({ code: 'OK', message: 'ok', data, hint: null, request_id: 'r' }), {
    headers: { 'Content-Type': 'application/json' },
  })
const err = (code: string, message: string) =>
  new Response(JSON.stringify({ code, message, data: null, hint: null, request_id: 'r' }), {
    headers: { 'Content-Type': 'application/json' },
  })

/** Mount /setup inside the real AuthProvider; sibling routes mark navigations. */
function renderSetup() {
  return render(
    <MemoryRouter initialEntries={['/setup']}>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<p>home-route</p>} />
          <Route path="/setup" element={<Setup />} />
          <Route path="/login" element={<p>login-route</p>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

/** Fill the form with valid credentials and submit. */
async function submitValid() {
  await userEvent.type(screen.getByLabelText('用户名'), 'admin')
  await userEvent.type(screen.getByLabelText('密码'), 'password123')
  await userEvent.click(screen.getByRole('button', { name: '创建并进入' }))
}

const calledUrls = (fetchMock: Mock) => fetchMock.mock.calls.map(([u]) => String(u))

describe('Setup', () => {
  it('shows both validation messages when the form is submitted empty', async () => {
    const fetchMock = vi.fn(async () => ok({ need_setup: true }))
    vi.stubGlobal('fetch', fetchMock)

    renderSetup()
    await userEvent.click(screen.getByRole('button', { name: '创建并进入' }))

    expect(await screen.findByText('用户名至少 3 个字符')).toBeTruthy()
    expect(screen.getByText('密码至少 8 位')).toBeTruthy()
    expect(calledUrls(fetchMock).some((u) => u.includes('/api/auth/setup'))).toBe(false)
  })

  it('creates the account, auto-logs in and enters /', async () => {
    const fetchMock = vi.fn(async (url: string | URL) => {
      if (String(url) === '/api/auth/setup') return ok(null)
      if (String(url) === '/api/auth/login') return ok({ token: 'tok-9' })
      // /api/auth/status probe and the post-login /api/auth/me lookup
      return ok({ need_setup: true })
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSetup()
    await submitValid()

    expect(await screen.findByText('home-route')).toBeTruthy()
    const urls = calledUrls(fetchMock)
    expect(urls).toContain('/api/auth/setup')
    // Setup must complete before the auto-login fires.
    expect(urls.indexOf('/api/auth/setup')).toBeLessThan(urls.indexOf('/api/auth/login'))
    expect(localStorage.getItem('ow_token')).toBe('tok-9')
  })

  it('maps SETUP_DONE to a notice with a login link', async () => {
    const fetchMock = vi.fn(async (url: string | URL) => {
      if (String(url) === '/api/auth/setup') return err('SETUP_DONE', '管理员已存在')
      return ok({ need_setup: true })
    })
    vi.stubGlobal('fetch', fetchMock)

    renderSetup()
    await submitValid()

    expect(await screen.findByText('初始化已完成，请直接登录')).toBeTruthy()
    const link = screen.getByRole('link', { name: '前往登录' })
    expect(link.getAttribute('href')).toBe('/login')
    // The failed setup must not auto-login.
    expect(calledUrls(fetchMock).some((u) => u.includes('/api/auth/login'))).toBe(false)
    expect(screen.queryByText('home-route')).toBeNull()
  })

  it('shows the done notice proactively when setup is already complete', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ok({ need_setup: false })),
    )

    renderSetup()
    expect(await screen.findByText('初始化已完成，请直接登录')).toBeTruthy()
    expect(screen.getByRole('link', { name: '前往登录' })).toBeTruthy()
  })
})
