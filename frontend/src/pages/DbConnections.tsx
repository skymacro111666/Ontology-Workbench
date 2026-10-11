import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import { ArrowLeftIcon } from 'lucide-react'
import ConnectionsPanel from '@/components/ConnectionsPanel'
import { Button } from '@/components/ui/button'

/** Database settings (/db-connections, user menu → 数据库设置): the
 *  standalone home for saved DB connections — list, create/edit, connect
 *  test, delete. The draft wizard links here via its 管理连接… entry. */
export default function DbConnections() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold">{t('conn.pageTitle')}</h1>
          <p className="text-ink-3 text-xs">{t('conn.pageSubtitle')}</p>
        </div>
        {/* Title-row right end, directly above 新建连接 — the page is a
            dead end without an explicit way back to where the user came. */}
        <Button variant="ghost" size="sm" className="mt-0.5" onClick={() => navigate(-1)}>
          <ArrowLeftIcon aria-hidden />
          {t('common.back')}
        </Button>
      </div>
      <ConnectionsPanel />
    </div>
  )
}
