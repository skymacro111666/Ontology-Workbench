import { describe, expect, it } from 'vitest'
import { credentialsSchema } from './credentials'

/** Boundary pins (backlog T5③): the exact min/max edges of both fields.
 *  Backend enforces the same limits — keep them in lockstep. */
describe('credentialsSchema boundaries', () => {
  const u = (n: number) => 'u'.repeat(n)
  const p = (n: number) => 'p'.repeat(n)

  it('accepts username at the 3-char minimum', () => {
    expect(credentialsSchema.safeParse({ username: u(3), password: p(8) }).success).toBe(true)
  })

  it('rejects a 2-char username', () => {
    expect(credentialsSchema.safeParse({ username: u(2), password: p(8) }).success).toBe(false)
  })

  it('accepts username at the 64-char maximum', () => {
    expect(credentialsSchema.safeParse({ username: u(64), password: p(8) }).success).toBe(true)
  })

  it('rejects a 65-char username', () => {
    expect(credentialsSchema.safeParse({ username: u(65), password: p(8) }).success).toBe(false)
  })

  it('accepts password at the 8-char minimum', () => {
    expect(credentialsSchema.safeParse({ username: u(3), password: p(8) }).success).toBe(true)
  })

  it('rejects a 7-char password', () => {
    expect(credentialsSchema.safeParse({ username: u(3), password: p(7) }).success).toBe(false)
  })

  it('accepts password at the 128-char maximum', () => {
    expect(credentialsSchema.safeParse({ username: u(3), password: p(128) }).success).toBe(true)
  })

  it('rejects a 129-char password', () => {
    expect(credentialsSchema.safeParse({ username: u(3), password: p(129) }).success).toBe(false)
  })
})
