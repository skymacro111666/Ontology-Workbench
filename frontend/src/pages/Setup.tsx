import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router'
import { useTranslation } from 'react-i18next'
import { ApiErr, api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { credentialErrorText, credentialsSchema, type Credentials } from '../auth/credentials'
import { errText } from '../i18n/errText'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/** One-shot first-run page: create the single admin account and enter. */
export default function Setup() {
  const { t } = useTranslation()
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
        setFormError(errText(err, t))
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
          <CardTitle className="text-xl">{t('setup.title')}</CardTitle>
          <CardDescription>{t('setup.subtitle')}</CardDescription>
        </CardHeader>
        <CardContent>
          {showDoneNotice && (
            <p role="status" className="text-sm text-muted-foreground">
              {t('setup.done')}
              <Link to="/login" className="ml-1 text-primary underline underline-offset-2">
                {t('setup.goLogin')}
              </Link>
            </p>
          )}
          {ready && probeError && (
            <p role="status" className="text-sm text-muted-foreground">
              {t('setup.offline')}
            </p>
          )}
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
            {formError && (
              <p role="alert" className="text-sm text-destructive">
                {formError}
              </p>
            )}
            <div className="flex flex-col gap-2">
              <Label htmlFor="username">{t('login.username')}</Label>
              <Input
                id="username"
                placeholder={t('login.username')}
                autoComplete="username"
                aria-invalid={errors.username ? true : undefined}
                {...form.register('username')}
              />
              {errors.username && (
                <p className="text-sm text-destructive">
                  {credentialErrorText('username', errors.username.type, t)}
                </p>
              )}
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">{t('login.password')}</Label>
              <Input
                id="password"
                type="password"
                placeholder={t('login.password')}
                autoComplete="new-password"
                aria-invalid={errors.password ? true : undefined}
                {...form.register('password')}
              />
              {errors.password && (
                <p className="text-sm text-destructive">
                  {credentialErrorText('password', errors.password.type, t)}
                </p>
              )}
            </div>
            <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
              {t('setup.submit')}
            </Button>
          </form>
          <p className="mt-4 text-center text-xs text-muted-foreground">
            {t('setup.footnote')}
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
