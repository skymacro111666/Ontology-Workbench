import { zodResolver } from '@hookform/resolvers/zod'
import { CopyIcon } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useParams } from 'react-router'
import { toast } from 'sonner'
import { z } from 'zod'
import { ApiErr, api } from '../api/client'
import type { ExportSiteResult } from '../api/types'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'

const exportSchema = z.object({
  outDir: z.string(),
})

type ExportForm = z.infer<typeof exportSchema>

/** One-click docs-site export: output-dir option, force switch, copyable result path. */
export default function Export() {
  const { oid = '' } = useParams()
  const [force, setForce] = useState(false)
  const [result, setResult] = useState<ExportSiteResult | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const form = useForm<ExportForm>({
    resolver: zodResolver(exportSchema),
    defaultValues: { outDir: '' },
  })
  const submitting = form.formState.isSubmitting

  const onSubmit = async (values: ExportForm) => {
    setFormError(null)
    try {
      setResult(
        await api.post<ExportSiteResult>(`/api/ontologies/${oid}/export/site`, {
          outDir: values.outDir.trim() || undefined,
          force,
        }),
      )
    } catch (err) {
      if (err instanceof ApiErr && err.code === 'VALIDATION_ERROR') {
        setFormError('目录非空，勾选覆盖或换一个')
      } else if (err instanceof ApiErr) {
        setFormError(err.message)
      } else {
        setFormError('导出失败，请稍后重试')
      }
    }
  }

  const copyDir = async () => {
    if (!result) return
    try {
      await navigator.clipboard.writeText(result.outputDir)
      toast.success('已复制')
    } catch {
      toast.error('复制失败')
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col gap-6 px-6 py-10">
      <Card className="rounded-card">
        <CardHeader>
          <CardTitle>导出文档站</CardTitle>
          <CardDescription>
            将本体一次性渲染为静态 HTML 文档站，写入服务器本地目录；导出完成后在服务器上打开输出目录中的
            index.html 即可浏览。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
            {formError && (
              <p role="alert" className="text-sm text-destructive">
                {formError}
              </p>
            )}
            <div className="flex flex-col gap-2">
              <Label htmlFor="outDir">输出目录（可选）</Label>
              <Input
                id="outDir"
                placeholder="留空使用默认：{数据目录}/exports/{id}-{时间戳}"
                disabled={submitting}
                {...form.register('outDir')}
              />
            </div>
            <div className="flex items-center gap-2">
              <Switch
                id="force"
                checked={force}
                onCheckedChange={setForce}
                disabled={submitting}
              />
              <Label htmlFor="force">覆盖非空目录</Label>
            </div>
            <Button type="submit" className="w-fit" disabled={submitting}>
              开始导出
            </Button>
          </form>
        </CardContent>
      </Card>

      {result && (
        <Card className="rounded-card">
          <CardHeader>
            <CardTitle>导出结果</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <code className="text-ink-2 min-w-0 flex-1 font-mono text-sm break-all">
                {result.outputDir}
              </code>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0"
                onClick={() => void copyDir()}
              >
                <CopyIcon />
                复制
              </Button>
            </div>
            <p className="text-ink-2 text-sm">
              共 {result.pageCount} 页（1 个索引页 + {result.pageCount - 1} 个实体页）
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
