import { Navigate, Outlet } from 'react-router'
import { useAuth } from './AuthContext'

/** Gates app routes: pending setup → /setup, missing token → /login. */
export default function ProtectedRoute() {
  const { ready, needSetup, token } = useAuth()
  if (!ready) return null
  if (needSetup) return <Navigate to="/setup" replace />
  if (!token) return <Navigate to="/login" replace />
  return <Outlet />
}
