import { PackageOpenIcon, SparklesIcon, UploadIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'

/** Zero-ontology guidance: load the pizza sample or open the import dialog. */
export default function EmptyState({
  onLoadSample,
  onImport,
}: {
  onLoadSample: () => void
  onImport: () => void
}) {
  return (
    <div className="border-line flex flex-col items-center gap-4 rounded-card border border-dashed px-6 py-16 text-center">
      <div
        aria-hidden
        className="bg-primary-soft text-primary flex size-12 items-center justify-center rounded-full"
      >
        <PackageOpenIcon className="size-6" />
      </div>
      <div className="flex flex-col gap-1">
        <p className="font-medium">还没有本体</p>
        <p className="text-ink-2 text-sm">载入内置示例快速体验，或导入你的本体文件</p>
      </div>
      <div className="flex gap-2">
        <Button onClick={onLoadSample}>
          <SparklesIcon />
          载入示例 pizza
        </Button>
        <Button variant="outline" onClick={onImport}>
          <UploadIcon />
          导入本体
        </Button>
      </div>
    </div>
  )
}
