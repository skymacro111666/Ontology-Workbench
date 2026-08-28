import { useState } from 'react'
import { toast } from 'sonner'
import { ApiErr, api } from '../api/client'
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
      setError('新密码需为 8–128 个字符')
      return
    }
    if (next !== confirm) {
      setError('两次输入的新密码不一致')
      return
    }
    setBusy(true)
    try {
      await api.put('/api/auth/password', { currentPassword: current, newPassword: next })
      toast.success('密码已修改')
      close()
    } catch (e) {
      setError(e instanceof ApiErr ? e.message : '修改失败，请稍后重试')
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>修改密码</DialogTitle>
          <DialogDescription>修改后当前登录保持有效，直至令牌自然过期。</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="pwd-current">当前密码</Label>
            <Input
              id="pwd-current"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="pwd-new">新密码</Label>
            <Input
              id="pwd-new"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="pwd-confirm">确认新密码</Label>
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
            取消
          </Button>
          <Button size="sm" onClick={() => void submit()} disabled={busy}>
            保存
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
