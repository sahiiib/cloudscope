import { Route, Routes } from 'react-router-dom';
import NatGateways from './network/NatGateways';
import NatGatewayDetails from './network/NatGatewayDetails';
import ElasticIPs from './network/ElasticIPs';
import ElasticIPDetails from './network/ElasticIPDetails';
import InstanceDetails from './instances/InstanceDetails';
import Search from './search/Search';
import LoadBalancerDetails from './load-balancers/LoadBalancerDetails';
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
      <Route path="/nat-gateways" element={<NatGateways />} />
      <Route path="/nat-gateways/:provider/:account/:region/:id" element={<NatGatewayDetails />} />
      <Route path="/elastic-ips" element={<ElasticIPs />} />
      <Route path="/elastic-ips/:provider/:account/:region/:id" element={<ElasticIPDetails />} />
      <Route path="/load-balancers" element={<LoadBalancers />} />
      <Route path="/load-balancers/:provider/:account/:region/:family/:id" element={<LoadBalancerDetails />} />
      <Route path="/instances/:provider/:account/:region/:id" element={<InstanceDetails />} />
      <Route path="/sync" element={<Sync />} />
      <Route path="/settings" element={<Settings />} />
      <Route path="/accounts" element={<Accounts />} />
      <Route path="*" element={<h1>Page not found</h1>} />
    </Route>
  </Routes>;
}
