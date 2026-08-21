import { useEffect, useState } from 'react'

/** Debounce a fast-changing value (search input) by `ms`. */
export function useDebounced<T>(value: T, ms = 150): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])

  return debounced
}
