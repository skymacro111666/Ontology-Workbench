import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'
import { AuthProvider } from '../auth/AuthContext'
import Setup from './Setup'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
})

function stubStatusProbe(body: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })),
  )
}

it('does not claim setup is done when the status probe fails', async () => {
  // Server unreachable: the probe error must not read as "setup completed"
  // (backlog T5①) — show a connection notice instead, keep the form usable.
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('network down')
    }),
  )
  render(
    <AuthProvider>
      <MemoryRouter>
        <Setup />
      </MemoryRouter>
    </AuthProvider>,
  )
  await waitFor(() => expect(screen.getByRole('status')).toBeTruthy())
  expect(screen.getByRole('status').textContent).toContain('无法连接服务器')
  expect(screen.queryByText('初始化已完成，请直接登录')).toBeNull()
  expect(screen.getByRole('button', { name: '创建并进入' })).toBeTruthy()
})

it('still shows the done notice when the probe genuinely reports completion', async () => {
  stubStatusProbe({ code: 'OK', message: 'ok', data: { need_setup: false }, hint: null, request_id: 'r' })
  render(
    <AuthProvider>
      <MemoryRouter>
        <Setup />
      </MemoryRouter>
    </AuthProvider>,
  )
  await waitFor(() => expect(screen.getByText('初始化已完成，请直接登录')).toBeTruthy())
})
