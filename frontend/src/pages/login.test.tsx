import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'
import Login from './Login'
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

/** Mount /login inside the real AuthProvider; sibling routes mark navigations. */
function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<p>home-route</p>} />
          <Route path="/login" element={<Login />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

const calledUrls = (fetchMock: Mock) => fetchMock.mock.calls.map(([u]) => String(u))

describe('Login', () => {
  it('shows both validation messages when the form is submitted empty', async () => {
    const fetchMock = vi.fn(async () => ok({ need_setup: false }))
    vi.stubGlobal('fetch', fetchMock)

    renderLogin()
    await userEvent.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByText('用户名至少 3 个字符')).toBeTruthy()
    expect(screen.getByText('密码至少 8 位')).toBeTruthy()
    // Client-side rejection must not touch the login endpoint.
    expect(calledUrls(fetchMock).some((u) => u.includes('/api/auth/login'))).toBe(false)
  })

  it('logs in and navigates to / on success', async () => {
    // Typed so the recorded call tuple carries `init` for the body assertion.
    const fetchMock = vi.fn<(url: string | URL, init?: RequestInit) => Promise<Response>>(
      async (url) => {
        if (String(url) === '/api/auth/login') return ok({ token: 'tok-1' })
        // /api/auth/status probe and the post-login /api/auth/me lookup
        return ok({ need_setup: false })
      },
    )
    vi.stubGlobal('fetch', fetchMock)

    renderLogin()
    await userEvent.type(screen.getByLabelText('用户名'), 'admin')
    await userEvent.type(screen.getByLabelText('密码'), 'password123')
    await userEvent.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByText('home-route')).toBeTruthy()
    const loginCall = fetchMock.mock.calls.find(([u]) => String(u) === '/api/auth/login')
    expect(loginCall).toBeTruthy()
    expect(JSON.parse(String(loginCall?.[1]?.body))).toEqual({
      username: 'admin',
      password: 'password123',
    })
    expect(localStorage.getItem('ow_token')).toBe('tok-1')
  })

  it('maps AUTH_INVALID_CREDENTIALS to the dedicated copy', async () => {
    const fetchMock = vi.fn(async (url: string | URL) => {
      if (String(url) === '/api/auth/login')
        return err('AUTH_INVALID_CREDENTIALS', 'server-side message')
      return ok({ need_setup: false })
    })
    vi.stubGlobal('fetch', fetchMock)

    renderLogin()
    await userEvent.type(screen.getByLabelText('用户名'), 'admin')
    await userEvent.type(screen.getByLabelText('密码'), 'password123')
    await userEvent.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByText('用户名或密码错误')).toBeTruthy()
    expect(screen.queryByText('home-route')).toBeNull()
  })
})
