import { Navigate, useParams, useSearchParams } from 'react-router'

/** Legacy /graph/:oid entry: the overview canvas now lives inside the
 *  workspace as its fourth view mode — redirect and keep deep links alive. */
export default function Graph() {
  const { oid = '' } = useParams()
  const [sp] = useSearchParams()
  const focus = sp.get('focus')
  const suffix = focus ? `&focus=${encodeURIComponent(focus)}` : ''
  return <Navigate replace to={`/browse/${oid}?view=overview${suffix}`} />
}
