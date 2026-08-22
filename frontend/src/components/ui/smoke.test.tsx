import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Button } from './button'

describe('shadcn ui base', () => {
  it('renders a button with variant classes', () => {
    render(<Button variant="outline">导入</Button>)
    expect(screen.getByRole('button', { name: '导入' })).toBeTruthy()
  })
})
