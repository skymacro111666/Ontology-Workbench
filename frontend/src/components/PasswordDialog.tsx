import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { api } from '../api/client'
import { errText } from '../i18n/errText'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

/** Account-menu password change: current + new + confirmation, client-side
 *  checks mirroring the backend (8–128 chars, match), server rejections
 *  inline. Success keeps the session — tokens run to their 7-day expiry
 *  by design (single-user deployment). */
export default function PasswordDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const close = () => {
    setCurrent('')
    setNext('')
    setConfirm('')
    setError(null)
    setBusy(false)
    onClose()
  }

  const submit = async () => {
    setError(null)
    if (next.length < 8 || next.length > 128) {
      setError(t('pwd.lenRule'))
      return
    }
    if (next !== confirm) {
      setError(t('pwd.mismatch'))
      return
    }
    setBusy(true)
    try {
      await api.put('/api/auth/password', { currentPassword: current, newPassword: next })
      toast.success(t('pwd.changed'))
      close()
    } catch (e) {
      setError(errText(e, t))
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('pwd.title')}</DialogTitle>
          <DialogDescription>{t('pwd.desc')}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="pwd-current">{t('pwd.current')}</Label>
            <Input
              id="pwd-current"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="pwd-new">{t('pwd.new')}</Label>
            <Input
              id="pwd-new"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="pwd-confirm">{t('pwd.confirm')}</Label>
            <Input
              id="pwd-confirm"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </div>
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={close} disabled={busy}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" onClick={() => void submit()} disabled={busy}>
            {t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
