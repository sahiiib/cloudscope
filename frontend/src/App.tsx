import { Route, Routes } from 'react-router-dom';
import InstanceDetails from './instances/InstanceDetails';
import Search from './search/Search';
import LoadBalancers from './load-balancers/LoadBalancers';
import Sync from './sync/Sync';
import Settings from './settings/Settings';
import Accounts from './settings/Accounts';
import Login from './auth/Login';
import ProtectedLayout from './auth/ProtectedLayout';

export default function App() {
  return <Routes>
    <Route path="/login" element={<Login />} />
    <Route element={<ProtectedLayout />}>
      <Route index element={<Search />} />
      <Route path="/load-balancers" element={<LoadBalancers />} />
      <Route path="/instances/:provider/:account/:region/:id" element={<InstanceDetails />} />
      <Route path="/sync" element={<Sync />} />
      <Route path="/settings" element={<Settings />} />
      <Route path="/accounts" element={<Accounts />} />
      <Route path="*" element={<h1>Page not found</h1>} />
    </Route>
  </Routes>;
}
