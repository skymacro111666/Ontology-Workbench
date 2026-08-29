import { PackageOpenIcon, SparklesIcon, UploadIcon } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'

/** Zero-ontology guidance: load the pizza sample or open the import dialog. */
export default function EmptyState({
  onLoadSample,
  onImport,
}: {
  onLoadSample: () => void
  onImport: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="border-line flex flex-col items-center gap-4 rounded-card border border-dashed px-6 py-16 text-center">
      <div
        aria-hidden
        className="bg-primary-soft text-primary flex size-12 items-center justify-center rounded-full"
      >
        <PackageOpenIcon className="size-6" />
      </div>
      <div className="flex flex-col gap-1">
        <p className="font-medium">{t('home.emptyTitle')}</p>
        <p className="text-ink-2 text-sm">{t('home.emptyHint')}</p>
      </div>
      <div className="flex gap-2">
        <Button onClick={onLoadSample}>
          <SparklesIcon />
          {t('home.loadSample', { name: 'pizza' })}
        </Button>
        <Button variant="outline" onClick={onImport}>
          <UploadIcon />
          {t('home.import')}
        </Button>
      </div>
    </div>
  )
}
