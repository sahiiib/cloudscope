import { Route, Routes } from 'react-router-dom';
import Search from './search/Search';
import Login from './auth/Login';
import ProtectedLayout from './auth/ProtectedLayout';

export default function App() {
  return <Routes>
    <Route path="/login" element={<Login />} />
    <Route element={<ProtectedLayout />}>
      <Route index element={<Search />} />
      <Route path="/sync" element={<><h1>Sync</h1><p>Sync history is coming soon.</p></>} />
      <Route path="/settings" element={<><h1>Settings</h1><p>Account settings are coming soon.</p></>} />
      <Route path="*" element={<h1>Page not found</h1>} />
    </Route>
  </Routes>;
}
