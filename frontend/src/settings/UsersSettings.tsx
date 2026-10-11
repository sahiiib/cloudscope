import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../api/client';
import type { ManagedUser } from '../api/types';
import CreateUser from './CreateUser';
import { settingsError } from './errors';

type Action = { user: ManagedUser; kind: 'activity' | 'mfa' };
export default function UsersSettings({ currentUserId, onSessionEnd }: { currentUserId: number; onSessionEnd: () => void }) {
  const client = useQueryClient();
  const [confirmation, setConfirmation] = useState<Action | null>(null);
  const users = useQuery({ queryKey: ['users'], queryFn: async ({ signal }): Promise<ManagedUser[]> => (await apiFetch('/api/users', { signal })).json() });
  const change = useMutation({
    mutationFn: async ({ user, kind }: Action) => {
      if (kind === 'mfa') await apiFetch(`/api/users/${user.id}/reset-mfa`, { method: 'POST' });
      else await apiFetch(`/api/users/${user.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: !user.is_active }) });
    },
    onSuccess: (_result, action) => {
      setConfirmation(null);
      if (action.user.id === currentUserId) onSessionEnd();
      else void client.invalidateQueries({ queryKey: ['users'] });
    },
  });
  function confirm(action: Action) { change.reset(); setConfirmation(action); }
  return <section className="settings-card settings-users" aria-labelledby="users-title"><h2 id="users-title">Users</h2>
    <p>Manage access. Deactivation and MFA resets sign out the affected user's sessions.</p>
    {users.isPending && <p role="status">Loading users…</p>}
    {users.isError && <p role="alert" className="error">Unable to {users.data ? 'refresh' : 'load'} users. <button onClick={() => void users.refetch()}>Retry users</button></p>}
    {Array.isArray(users.data) && <div className="settings-table-scroll"><table className="settings-table"><thead><tr><th>Username</th><th>Role</th><th>Status</th><th>MFA</th><th>Last login</th><th>Actions</th></tr></thead>
      <tbody>{users.data.map(user => <tr key={user.id}><td>{user.username}{user.id === currentUserId && ' (you)'}</td><td>{user.is_admin ? 'Admin' : 'Member'}</td><td>{user.is_active ? 'Active' : 'Inactive'}</td><td>{user.mfa_enabled ? 'Enabled' : 'Disabled'}</td>
        <td>{user.last_login_at ? <time dateTime={user.last_login_at}>{new Date(user.last_login_at).toLocaleString()}</time> : 'Never'}</td>
        <td><div className="settings-actions"><button className="secondary" disabled={change.isPending} onClick={() => confirm({ user, kind: 'activity' })}>{user.is_active ? 'Deactivate' : 'Reactivate'} {user.username}</button>
          <button className="secondary" disabled={change.isPending} onClick={() => confirm({ user, kind: 'mfa' })}>Reset MFA for {user.username}</button></div></td></tr>)}</tbody></table>
      {users.data.length === 0 && <p>No users found.</p>}
    </div>}
    {confirmation && <div className="settings-confirm" role="group" aria-label="Confirm user change">
      <p>{confirmation.kind === 'mfa' ? 'Reset MFA for' : confirmation.user.is_active ? 'Deactivate' : 'Reactivate'} <strong>{confirmation.user.username}</strong>?</p>
      {confirmation.user.id === currentUserId && <p>This will sign you out.</p>}
      <div className="settings-actions"><button disabled={change.isPending} onClick={() => change.mutate(confirmation)}>Confirm change</button>
        <button className="secondary" disabled={change.isPending} onClick={() => { setConfirmation(null); change.reset(); }}>Cancel</button></div>
    </div>}
    {change.isError && <p role="alert" className="error">{settingsError(change.error, 'Unable to update user.', 'The last active administrator cannot be deactivated.')}</p>}
    {change.isSuccess && <p role="status">User updated.</p>}
    <CreateUser onCreated={() => void client.invalidateQueries({ queryKey: ['users'] })} />
  </section>;
}
