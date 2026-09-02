import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router'
import { useTranslation } from 'react-i18next'
import { AuthProvider } from './auth/AuthContext'
import ProtectedRoute from './auth/ProtectedRoute'
import AppShell from './components/AppShell'
import Login from './pages/Login'
import Setup from './pages/Setup'

// Workspace pages load lazily: each page (with its components) becomes its
// own chunk, keeping the entry payload to shell + auth pages.
const Home = lazy(() => import('./pages/Home'))
const Browse = lazy(() => import('./pages/Browse'))
const Graph = lazy(() => import('./pages/Graph'))

/** Route table; protected area sits behind ProtectedRoute inside the AppShell. */
export default function App() {
  const { t } = useTranslation()
  return (
    <AuthProvider>
      <Suspense fallback={<div className="text-ink-3 py-16 text-center text-sm">{t('common.loading')}</div>}>
        <Routes>
          <Route path="/setup" element={<Setup />} />
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedRoute />}>
            <Route element={<AppShell />}>
              <Route path="/" element={<Home />} />
              <Route path="/browse/:oid" element={<Browse />} />
              <Route path="/graph/:oid" element={<Graph />} />
            </Route>
          </Route>
        </Routes>
      </Suspense>
    </AuthProvider>
  )
}
