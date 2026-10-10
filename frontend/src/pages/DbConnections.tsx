import { useTranslation } from 'react-i18next'
import ConnectionsPanel from '@/components/ConnectionsPanel'

/** Database settings (/db-connections, user menu → 数据库设置): the
 *  standalone home for saved DB connections — list, create/edit, connect
 *  test, delete. The draft wizard links here via its 管理连接… entry. */
export default function DbConnections() {
  const { t } = useTranslation()
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-6">
      <div>
        <h1 className="text-lg font-semibold">{t('conn.pageTitle')}</h1>
        <p className="text-ink-3 text-xs">{t('conn.pageSubtitle')}</p>
      </div>
      <ConnectionsPanel />
    </div>
  )
}
