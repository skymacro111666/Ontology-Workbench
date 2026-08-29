import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router'
import { ApiErr, api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { credentialsSchema, type Credentials } from '../auth/credentials'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/** One-shot first-run page: create the single admin account and enter. */
export default function Setup() {
  const { login, needSetup, ready, probeError } = useAuth()
  const navigate = useNavigate()
  const [formError, setFormError] = useState<string | null>(null)
  // The status probe may already know setup is done before any submit happens.
  const [done, setDone] = useState(false)
  const showDoneNotice = done || (ready && !needSetup && !probeError)
  const form = useForm<Credentials>({
    resolver: zodResolver(credentialsSchema),
    defaultValues: { username: '', password: '' },
  })
  const errors = form.formState.errors

  const onSubmit = async (values: Credentials) => {
    setFormError(null)
    try {
      await api.post('/api/auth/setup', values)
      await login(values.username, values.password)
      navigate('/')
    } catch (err) {
      if (err instanceof ApiErr && err.code === 'SETUP_DONE') {
        setDone(true)
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
          <CardTitle className="text-xl">初始化 Ontology Workbench</CardTitle>
          <CardDescription>创建管理员账号（仅需一次）</CardDescription>
        </CardHeader>
        <CardContent>
          {showDoneNotice && (
            <p role="status" className="text-sm text-muted-foreground">
              初始化已完成，请直接登录
              <Link to="/login" className="ml-1 text-primary underline underline-offset-2">
                前往登录
              </Link>
            </p>
          )}
          {ready && probeError && (
            <p role="status" className="text-sm text-muted-foreground">
              无法连接服务器，请检查服务状态后重试
            </p>
          )}
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
                autoComplete="new-password"
                aria-invalid={errors.password ? true : undefined}
                {...form.register('password')}
              />
              {errors.password && (
                <p className="text-sm text-destructive">{errors.password.message}</p>
              )}
            </div>
            <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
              创建并进入
            </Button>
          </form>
          <p className="mt-4 text-center text-xs text-muted-foreground">
            凭据仅存于本地数据库，不会离开这台服务器
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
