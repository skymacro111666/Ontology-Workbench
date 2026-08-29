import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import PasswordDialog from './PasswordDialog'

/* The account-menu password dialog: client-side checks mirror the backend
   (length, confirmation match) without a request; submissions carry the
   camelCase body and server rejections surface inline, dialog stays open. */

const OK_ENV = {
  code: 'OK',
  message: 'ok',
  data: { ok: true },
  hint: null,
  request_id: 'r',
}
const rejectEnv = (message: string) =>
  new Response(
    JSON.stringify({
      code: 'AUTH_INVALID_CREDENTIALS',
      message,
      data: null,
      hint: null,
      request_id: 'r',
    }),
    { headers: { 'Content-Type': 'application/json' } },
  )

function renderDialog(onClose = vi.fn()) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(OK_ENV)))
  vi.stubGlobal('fetch', fetchMock)
  return { onClose, fetchMock, ...render(<PasswordDialog open onClose={onClose} />) }
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('PasswordDialog', () => {
  it('rejects a mismatching confirmation inline without a request', async () => {
    const { fetchMock } = renderDialog()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('当前密码'), 'long-enough-pw')
    await user.type(screen.getByLabelText('新密码'), 'brand-new-long-pw')
    await user.type(screen.getByLabelText('确认新密码'), 'different-long-pw')
    await user.click(screen.getByRole('button', { name: '保存' }))
    expect(screen.getByRole('alert').textContent).toContain('两次输入的新密码不一致')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('rejects a short new password inline', async () => {
    const { fetchMock } = renderDialog()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('新密码'), 'short')
    await user.type(screen.getByLabelText('确认新密码'), 'short')
    await user.click(screen.getByRole('button', { name: '保存' }))
    expect(screen.getByRole('alert').textContent).toContain('8–128')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('submits the camelCase body and closes on success', async () => {
    const { onClose, fetchMock } = renderDialog()
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('当前密码'), 'long-enough-pw')
    await user.type(screen.getByLabelText('新密码'), 'brand-new-long-pw')
    await user.type(screen.getByLabelText('确认新密码'), 'brand-new-long-pw')
    await user.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/auth/password',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ currentPassword: 'long-enough-pw', newPassword: 'brand-new-long-pw' }),
      }),
    )
  })

  it('surfaces the server rejection inline and stays open', async () => {
    const onClose = vi.fn()
    const fetchMock = vi.fn(async () => rejectEnv('Current password is incorrect'))
    vi.stubGlobal('fetch', fetchMock)
    render(<PasswordDialog open onClose={onClose} />)
    const user = userEvent.setup()
    await user.type(screen.getByLabelText('当前密码'), 'wrong-password')
    await user.type(screen.getByLabelText('新密码'), 'brand-new-long-pw')
    await user.type(screen.getByLabelText('确认新密码'), 'brand-new-long-pw')
    await user.click(screen.getByRole('button', { name: '保存' }))
    // errText maps AUTH_INVALID_CREDENTIALS to the localized text — the raw
    // envelope message ('Current password is incorrect') is no longer shown.
    expect((await screen.findByRole('alert')).textContent).toContain('用户名或密码错误')
    expect(onClose).not.toHaveBeenCalled()
  })
})
