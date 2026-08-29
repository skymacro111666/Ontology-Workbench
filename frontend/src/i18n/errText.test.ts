import { expect, it } from 'vitest'
import { ApiErr } from '../api/client'
import i18n from './index'
import { errText } from './errText'

const t = i18n.t

it('maps known ApiErr codes to localized text', () => {
  const e = new ApiErr('EDIT_CONFLICT', 'The file changed since it was loaded', null, 'r')
  expect(errText(e, t)).toBe('内容已被其他会话修改，请刷新后重试')
})

it('keeps raw detail for dynamic-message codes', () => {
  const e = new ApiErr('VALIDATION_ERROR', "Invalid name 'x'", null, 'r')
  expect(errText(e, t)).toBe("输入不合法：Invalid name 'x'")
})

it('falls back to the raw message for unmapped codes', () => {
  const e = new ApiErr('SOMETHING_ELSE', 'boom', null, 'r')
  expect(errText(e, t)).toBe('boom')
})

it('uses the common fallback for non-ApiErr errors', () => {
  expect(errText(new TypeError('network down'), t)).toBe('操作失败，请稍后重试')
})
