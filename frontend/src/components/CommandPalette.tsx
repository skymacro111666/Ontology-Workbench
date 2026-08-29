import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useMatch, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { api } from '../api/client'
import type { SearchHit } from '../api/types'
import { LAST_OID_KEY } from '../auth/AuthContext'
import { useDebounced } from '../hooks/useDebounced'
import { useBrowseStore } from '../stores/browseStore'
import { Badge } from '@/components/ui/badge'
import {
  CommandDialog,
  CommandEmpty,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'

/** Global ⌘K palette: debounced /search over the active (or last) ontology.
 *  Picking a hit routes to /browse/:oid?eid=… and asks the class tree to
 *  expand-reveal it (spec §7.4). */
export default function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const debounced = useDebounced(q, 150)
  const navigate = useNavigate()
  const reveal = useBrowseStore((s) => s.reveal)
  // The shell outlives the /:oid routes, so match the oid off the location.
  const browse = useMatch('/browse/:oid')
  const graph = useMatch('/graph/:oid')
  const exportMatch = useMatch('/export/:oid')
  const oid =
    browse?.params.oid ?? graph?.params.oid ?? exportMatch?.params.oid ?? localStorage.getItem(LAST_OID_KEY)

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen(true)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  // Hits arrive pre-filtered by the server, so cmdk's own filter is off.
  const { data: hits, isPending, isError } = useQuery({
    enabled: open && oid !== null && debounced.trim().length > 0,
    queryKey: ['search', oid, debounced],
    queryFn: () =>
      api.get<SearchHit[]>(
        `/api/ontologies/${oid as string}/search?q=${encodeURIComponent(debounced)}`,
      ),
  })

  const choose = (hit: SearchHit) => {
    if (!oid) {
      toast('先打开一个本体')
      return
    }
    reveal(hit.eid)
    setOpen(false)
    setQ('')
    navigate(`/browse/${oid}?eid=${encodeURIComponent(hit.eid)}`)
  }

  return (
    <CommandDialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (!o) setQ('')
      }}
      commandProps={{ shouldFilter: false }}
    >
      <p className="text-muted-foreground border-border border-b px-3 py-1.5 text-xs">
        Ctrl/⌘ K 打开 · Esc 关闭
      </p>
      <CommandInput value={q} onValueChange={setQ} placeholder="搜索类 / 属性…" />
      <CommandList>
        {/* No hits is only meaningful once the fetch has settled — while
            isPending (first fetch and every queryKey switch) the empty
            state would flash beside nothing. A rejected search is an error,
            not "no matches". */}
        {isError ? (
          <CommandEmpty>搜索失败，请稍后重试</CommandEmpty>
        ) : !isPending && debounced.trim() ? (
          <CommandEmpty>无匹配结果</CommandEmpty>
        ) : null}
        {(hits ?? []).map((hit) => (
          <CommandItem key={hit.eid} value={hit.eid} onSelect={() => choose(hit)}>
            <span className="font-mono text-sm">{hit.curie}</span>
            <Badge variant="secondary">{hit.matchedField}</Badge>
            <span className="text-muted-foreground ml-auto text-xs">{hit.type}</span>
          </CommandItem>
        ))}
      </CommandList>
    </CommandDialog>
  )
}
