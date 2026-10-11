import { useQueryClient } from '@tanstack/react-query';
import { useNavigate, useOutletContext } from 'react-router-dom';
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
  return <section className="settings-page"><h1>Settings</h1><p>Signed in as {user.username}</p>
    <div className="settings-grid"><PasswordSettings onSessionEnd={endSession} /><MFASettings enabled={user.mfa_enabled} onChanged={mfaChanged} /></div>
    {user.is_admin && <UsersSettings currentUserId={user.id} onSessionEnd={endSession} />}
  </section>;
}
