import { useOutletContext } from 'react-router-dom';
import type { AuthUser } from '../api/types';
import CloudAccounts from './CloudAccounts';
import './settings.css';

export default function Accounts() {
  const user = useOutletContext<AuthUser>();
  return <section className="settings-page">
    <div className="page-heading"><span className="eyebrow">Connections</span><h1>Accounts</h1>
      <p>Your cloud accounts and collection access, in one place.</p></div>
    {user.is_admin ? <CloudAccounts /> : <p role="alert">Only administrators can manage cloud accounts.</p>}
  </section>;
}
