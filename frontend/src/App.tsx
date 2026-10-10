import { Route, Routes } from 'react-router-dom';
import Sync from './sync/Sync';
import Login from './auth/Login';
import ProtectedLayout from './auth/ProtectedLayout';

export default function App() {
  return <Routes>
    <Route path="/login" element={<Login />} />
    <Route element={<ProtectedLayout />}>
      <Route index element={<><h1>Search</h1><p>Instance search is coming soon.</p></>} />
      <Route path="/sync" element={<Sync />} />
      <Route path="/settings" element={<><h1>Settings</h1><p>Account settings are coming soon.</p></>} />
      <Route path="*" element={<h1>Page not found</h1>} />
    </Route>
  </Routes>;
}
