import { z } from 'zod'

/** Credential rules shared by Login and Setup (backlog T5②: one source, not
 *  two verbatim copies). Mirrors the backend's own limits. */
export const credentialsSchema = z.object({
  username: z.string().min(3, '用户名至少 3 个字符').max(64, '用户名不超过 64 个字符'),
  password: z.string().min(8, '密码至少 8 位').max(128, '密码不超过 128 位'),
})

export type Credentials = z.infer<typeof credentialsSchema>
