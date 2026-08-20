import { Route, Routes } from 'react-router'
import { AuthProvider } from './auth/AuthContext'
import ProtectedRoute from './auth/ProtectedRoute'
import Browse from './pages/Browse'
import Export from './pages/Export'
import Graph from './pages/Graph'
import Home from './pages/Home'
import Login from './pages/Login'
import Setup from './pages/Setup'

/** Route table; protected area sits behind ProtectedRoute. */
export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/setup" element={<Setup />} />
        <Route path="/login" element={<Login />} />
        <Route element={<ProtectedRoute />}>
          <Route path="/" element={<Home />} />
          <Route path="/browse/:oid" element={<Browse />} />
          <Route path="/graph/:oid" element={<Graph />} />
          <Route path="/export/:oid" element={<Export />} />
        </Route>
      </Routes>
    </AuthProvider>
  )
}
