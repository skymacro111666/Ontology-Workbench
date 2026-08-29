import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it } from 'vitest'
import i18n from '../../i18n'
import { LangToggle } from './LangToggle'

afterEach(() => {
  cleanup()
  localStorage.clear()
  void i18n.changeLanguage('zh')
  document.documentElement.lang = 'zh'
})

it('switches language live and persists the choice', async () => {
  render(<LangToggle />)
  expect(document.documentElement.lang).toBe('zh')
  await userEvent.click(screen.getByRole('button', { name: 'EN' }))
  expect(i18n.language).toBe('en')
  expect(localStorage.getItem('ow_lang')).toBe('en')
  expect(document.documentElement.lang).toBe('en')
})
