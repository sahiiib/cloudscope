import { Route, Routes } from 'react-router-dom';
import Settings from './settings/Settings';
import Login from './auth/Login';
import ProtectedLayout from './auth/ProtectedLayout';

export default function App() {
  return <Routes>
    <Route path="/login" element={<Login />} />
    <Route element={<ProtectedLayout />}>
      <Route index element={<><h1>Search</h1><p>Instance search is coming soon.</p></>} />
      <Route path="/sync" element={<><h1>Sync</h1><p>Sync history is coming soon.</p></>} />
      <Route path="/settings" element={<Settings />} />
      <Route path="*" element={<h1>Page not found</h1>} />
    </Route>
  </Routes>;
}
