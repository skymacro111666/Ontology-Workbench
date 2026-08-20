import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from '../api/client'

export const TOKEN_KEY = 'ow_token'
export const LAST_OID_KEY = 'ow_last'

export interface AuthUser {
  id: string
  username: string
}

interface AuthState {
  user: AuthUser | null
  token: string | null
  needSetup: boolean
  /** False until the setup-status probe settles; gates routing decisions. */
  ready: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

/** Holds auth state; on mount probes setup status and the current user. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY))
  const [needSetup, setNeedSetup] = useState(false)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    api
      .get<{ need_setup: boolean }>('/api/auth/status')
      .then((data) => setNeedSetup(data.need_setup))
      .catch(() => setNeedSetup(false))
      .finally(() => setReady(true))
  }, [])

  useEffect(() => {
    if (!token) return
    api
      .get<AuthUser>('/api/auth/me')
      .then((me) => setUser({ id: me.id, username: me.username }))
      .catch(() => {
        /* 401-class codes already clear the token and redirect via the client */
      })
  }, [token])

  const login = useCallback(async (username: string, password: string) => {
    const data = await api.post<{ token: string }>('/api/auth/login', { username, password })
    localStorage.setItem(TOKEN_KEY, data.token)
    setToken(data.token)
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ user, token, needSetup, ready, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
