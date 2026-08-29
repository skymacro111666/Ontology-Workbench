import { useQuery } from '@tanstack/react-query'
import { CheckIcon, ChevronDownIcon } from 'lucide-react'
import { useMatch, useNavigate } from 'react-router'
import { useTranslation } from 'react-i18next'
import { api } from '../api/client'
import type { OntologySummary } from '../api/types'
import { LAST_OID_KEY } from '../auth/AuthContext'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

/** Topbar ontology picker: lists loaded ontologies, opens the picked one in Browse. */
export default function OntologySwitcher() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  // Layout-level component, so route params must be read from the URL matches.
  const browseOid = useMatch('/browse/:oid')?.params.oid
  const graphOid = useMatch('/graph/:oid')?.params.oid
  const exportOid = useMatch('/export/:oid')?.params.oid
  const currentOid = browseOid ?? graphOid ?? exportOid

  const { data, isPending, isError } = useQuery({
    queryKey: ['ontologies'],
    queryFn: () => api.get<{ items: OntologySummary[]; total: number }>('/api/ontologies'),
  })
  const items = data?.items ?? []
  const current = items.find((o) => o.id === currentOid)

  const open = (id: string) => {
    localStorage.setItem(LAST_OID_KEY, id)
    navigate(`/browse/${id}`)
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm">
          {current?.title ?? t('shell.pickOntology')}
          <ChevronDownIcon />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {isPending ? (
          <DropdownMenuItem disabled>{t('common.loading')}</DropdownMenuItem>
        ) : isError ? (
          // A failed fetch must not masquerade as an empty shelf (T4①).
          <DropdownMenuItem disabled>{t('shell.loadFailed')}</DropdownMenuItem>
        ) : items.length === 0 ? (
          <DropdownMenuItem disabled>{t('shell.noOntologies')}</DropdownMenuItem>
        ) : (
          items.map((o) => (
            <DropdownMenuItem key={o.id} onSelect={() => open(o.id)}>
              {o.id === currentOid ? <CheckIcon /> : <span className="size-4" aria-hidden />}
              {o.title}
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
