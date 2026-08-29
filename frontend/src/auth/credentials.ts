import type { TFunction } from 'i18next'
import { z } from 'zod'

/** Credential rules shared by Login and Setup (backlog T5②: one source, not
 *  two verbatim copies). Mirrors the backend's own limits. The schema carries
 *  no messages — pages localize via credentialErrorText so both languages
 *  render without rebuilding the resolver. */
export const credentialsSchema = z.object({
  username: z.string().min(3).max(64),
  password: z.string().min(8).max(128),
})

export type Credentials = z.infer<typeof credentialsSchema>

/** Localized message for a react-hook-form FieldError of one of the two
 *  fields, keyed by the zod issue code RHF reports in `type`. */
export function credentialErrorText(
  field: 'username' | 'password',
  type: string | undefined,
  t: TFunction,
): string | undefined {
  if (!type) return undefined
  if (type === 'too_small') return t(field === 'username' ? 'login.usernameMin' : 'login.passwordMin')
  if (type === 'too_big') return t(field === 'username' ? 'login.usernameMax' : 'login.passwordMax')
  return t('err.VALIDATION_ERROR')
}
