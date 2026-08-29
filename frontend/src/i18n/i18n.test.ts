import { expect, it } from 'vitest'
import i18n from './index'

it('boots with both locales and switches live', async () => {
  expect(i18n.t('common.loading')).toBe('加载中…') // MODE=test pins zh
  await i18n.changeLanguage('en')
  expect(i18n.t('common.loading')).toBe('Loading…')
  await i18n.changeLanguage('zh')
})

it('maps every error code in both languages', () => {
  const codes = [
    'AUTH_REQUIRED',
    'TOKEN_EXPIRED',
    'AUTH_INVALID_CREDENTIALS',
    'SETUP_DONE',
    'NOT_FOUND',
    'DUPLICATE_FILENAME',
    'DUPLICATE_ENTITY',
    'EDIT_CONFLICT',
    'PARSE_FAILED',
    'UPLOAD_TOO_LARGE',
    'UNSUPPORTED_FORMAT',
    'VALIDATION_ERROR',
    'INTERNAL_ERROR',
  ]
  for (const c of codes) {
    const zh = i18n.t(`err.${c}`, { lng: 'zh' })
    const en = i18n.t(`err.${c}`, { lng: 'en' })
    expect(zh, c).not.toBe(`err.${c}`)
    expect(en, c).not.toBe(`err.${c}`)
  }
})
