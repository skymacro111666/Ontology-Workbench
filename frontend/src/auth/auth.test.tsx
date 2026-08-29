import { cleanup, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router'
import { AuthProvider, useAuth } from './AuthContext'
import ProtectedRoute from './ProtectedRoute'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

function stubFetch(body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })),
  )
}

function renderRoutes() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/setup" element={<div>setup page</div>} />
          <Route path="/login" element={<div>login page</div>} />
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<div>home page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  )
}

describe('ProtectedRoute', () => {
  it('redirects to /login when no token is stored', async () => {
    stubFetch({ code: 'OK', message: 'ok', data: { need_setup: false }, hint: null, request_id: 'r' })
    renderRoutes()
    await waitFor(() => expect(screen.getByText('login page')).toBeTruthy())
    expect(screen.queryByText('home page')).toBeNull()
  })

  it('redirects to /setup when setup is pending', async () => {
    stubFetch({ code: 'OK', message: 'ok', data: { need_setup: true }, hint: null, request_id: 'r' })
    renderRoutes()
    await waitFor(() => expect(screen.getByText('setup page')).toBeTruthy())
  })

  it('renders the protected content when a token exists', async () => {
    localStorage.setItem('ow_token', 'tok')
    stubFetch({ code: 'OK', message: 'ok', data: { id: 'u1', username: 'admin' }, hint: null, request_id: 'r' })
    renderRoutes()
    await waitFor(() => expect(screen.getByText('home page')).toBeTruthy())
  })
})

describe('AuthProvider status probe', () => {
  it('signals probeError when the status probe fails (backlog T5①)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('network down')
      }),
    )
    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    await waitFor(() => expect(result.current.ready).toBe(true))
    expect(result.current.probeError).toBe(true)
    expect(result.current.needSetup).toBe(false)
  })

  it('keeps probeError clear when the probe succeeds', async () => {
    stubFetch({ code: 'OK', message: 'ok', data: { need_setup: true }, hint: null, request_id: 'r' })
    const { result } = renderHook(() => useAuth(), { wrapper: AuthProvider })
    await waitFor(() => expect(result.current.ready).toBe(true))
    expect(result.current.probeError).toBe(false)
    expect(result.current.needSetup).toBe(true)
  })
})
