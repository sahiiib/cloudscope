import { useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useOutletContext } from 'react-router-dom';
import type { AuthUser } from '../api/types';
import PasswordSettings from './PasswordSettings';
import MFASettings from './MFASettings';
import UsersSettings from './UsersSettings';
import './settings.css';

export default function Settings() {
  const user = useOutletContext<AuthUser>();
  const client = useQueryClient();
  const navigate = useNavigate();
  function endSession() { client.clear(); navigate('/login', { replace: true }); }
  function mfaChanged(enabled: boolean) {
    client.setQueryData<AuthUser>(['auth', 'me'], { ...user, mfa_enabled: enabled });
    void client.invalidateQueries({ queryKey: ['auth', 'me'] });
    void client.invalidateQueries({ queryKey: ['users'] });
  }
  return <section className="settings-page">
    <div className="page-heading"><span className="eyebrow">Workspace</span><h1>Settings</h1>
      <p>Signed in as {user.username}. Cloud accounts are managed on the {user.is_admin ? <Link to="/accounts">Accounts</Link> : 'Accounts'} page.</p></div>
    <h2 className="settings-section-title">Your security</h2>
    <div className="settings-grid"><PasswordSettings onSessionEnd={endSession} /><MFASettings enabled={user.mfa_enabled} onChanged={mfaChanged} /></div>
    {user.is_admin && <><h2 className="settings-section-title">Administration</h2><UsersSettings currentUserId={user.id} onSessionEnd={endSession} /></>}
  </section>;
}
