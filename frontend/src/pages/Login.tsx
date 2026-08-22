import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router'
import { z } from 'zod'
import { ApiErr } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const credentialsSchema = z.object({
  username: z.string().min(3, '用户名至少 3 个字符').max(64, '用户名不超过 64 个字符'),
  password: z.string().min(8, '密码至少 8 位').max(128, '密码不超过 128 位'),
})

type Credentials = z.infer<typeof credentialsSchema>

/** JWT login; error copy branches on the envelope code. */
export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<Credentials>({
    resolver: zodResolver(credentialsSchema),
    defaultValues: { username: '', password: '' },
  })
  const errors = form.formState.errors

  const onSubmit = async (values: Credentials) => {
    setFormError(null)
    try {
      await login(values.username, values.password)
      navigate('/')
    } catch (err) {
      if (err instanceof ApiErr && err.code === 'AUTH_INVALID_CREDENTIALS') {
        setFormError('用户名或密码错误')
      } else if (err instanceof ApiErr) {
        setFormError(err.message)
      } else {
        throw err
      }
    }
  }

  return (
    <div className="bg-canvas canvas-dots relative flex min-h-dvh items-center justify-center overflow-hidden p-4">
      {/* Decorative radial wash above the dot grid, behind the card. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse 640px 420px at 50% 30%, var(--color-primary-soft), transparent 70%)',
        }}
      />
      <Card className="relative w-full max-w-[400px] rounded-modal">
        <CardHeader className="text-center">
          <CardTitle className="text-xl">Ontology Workbench</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
            {formError && (
              <p role="alert" className="text-sm text-destructive">
                {formError}
              </p>
            )}
            <div className="flex flex-col gap-2">
              <Label htmlFor="username">用户名</Label>
              <Input
                id="username"
                placeholder="用户名"
                autoComplete="username"
                aria-invalid={errors.username ? true : undefined}
                {...form.register('username')}
              />
              {errors.username && (
                <p className="text-sm text-destructive">{errors.username.message}</p>
              )}
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                placeholder="密码"
                autoComplete="current-password"
                aria-invalid={errors.password ? true : undefined}
                {...form.register('password')}
              />
              {errors.password && (
                <p className="text-sm text-destructive">{errors.password.message}</p>
              )}
            </div>
            <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
              登录
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
