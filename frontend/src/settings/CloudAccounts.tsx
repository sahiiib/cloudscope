import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiFetch } from '../api/client';
import type { AccountAccessResult, AccountSummary } from '../api/types';
import AccountForm from './AccountForm';
import { settingsError } from './errors';

function AccountRow({ account, onEdit, onChanged, editing }: { editing: boolean; account: AccountSummary; onEdit: () => void; onChanged: () => Promise<void> }) {
  const [confirm, setConfirm] = useState(false);
  const [adoptConfirm, setAdoptConfirm] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const path = `/api/accounts/${account.provider}/${account.account_id}` as const;
  const activity = useMutation({
    mutationFn: async () => { await apiFetch(path, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: !account.enabled, expected_version: account.configuration_version }) }); },
    onSuccess: async () => { setConfirm(false); await onChanged(); },
  });
  const adopt = useMutation({
    mutationFn: async () => { await apiFetch(`${path}/adopt`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmed: true, expected_version: account.configuration_version }) }); },
    onSuccess: async () => { setAdoptConfirm(false); await onChanged(); },
  });
  const remove = useMutation({
    mutationFn: async () => { await apiFetch(path, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmed: true, expected_version: account.configuration_version }) }); },
    onSuccess: async () => { setDeleteConfirm(false); await onChanged(); },
  });
  const access = useMutation({ mutationFn: async (): Promise<AccountAccessResult> => (await apiFetch(`${path}/test`, { method: 'POST' })).json() });
  const { reset: resetAccess } = access;
  useEffect(() => { resetAccess(); }, [account.role_arn, account.external_id, account.regions, account.configuration_version, resetAccess]);
  return <tr>
    <td>{account.provider === 'aws' ? 'AWS' : 'Alibaba'}</td><td>{account.name}</td><td>{account.cloud_alias ?? '–'}</td><td>{account.account_id}</td>
    <td>{account.regions === 'all' ? 'All' : account.regions.join(', ')}</td><td className="account-role">{account.connection_mode === 'dedicated' ? 'Dedicated Access Key' : account.role_arn ?? 'Runtime credentials'}</td>
    <td>{account.source === 'file' ? 'Managed by accounts.yaml' : 'UI'}</td><td>{account.enabled ? 'Enabled' : 'Disabled'}</td>
    <td>{account.last_success_at ? <time dateTime={account.last_success_at}>{new Date(account.last_success_at).toLocaleString()}</time> : 'Never'}</td><td>{account.instance_count}</td>
    <td><div className="settings-actions">
      {account.source === 'file' && <button className="secondary" disabled={adopt.isPending || editing} onClick={() => { adopt.reset(); setAdoptConfirm(true); }}>Manage {account.name} in web</button>}
      {account.source === 'ui' && <><button className="secondary" disabled={activity.isPending || editing} onClick={onEdit}>Edit {account.name}</button>
        <button className="secondary" disabled={activity.isPending} onClick={() => { activity.reset(); setConfirm(true); }}>{account.enabled ? 'Disable' : 'Enable'} {account.name}</button></>}
      <button className="secondary" disabled={access.isPending} onClick={() => access.mutate()}>{access.isPending ? 'Testing…' : `Test access for ${account.name}`}</button>
      <button className="secondary" disabled={remove.isPending || editing} onClick={() => { remove.reset(); setDeleteConfirm(true); }}>Delete {account.name}</button>
    </div>
      {deleteConfirm && <div className="settings-confirm" role="group" aria-label={`Confirm deletion for ${account.name}`}>
        <p>Delete <strong>{account.name}</strong> from Cloudscope?</p><p>Collection will stop and this account’s inventory will be hidden. Your cloud resources are unchanged. Re-add the same account to restore its saved history.</p>
        <div className="settings-actions"><button disabled={remove.isPending} onClick={() => remove.mutate()}>Delete account</button><button className="secondary" disabled={remove.isPending} onClick={() => { setDeleteConfirm(false); remove.reset(); }}>Cancel</button></div>
      </div>}
      {remove.isError && <p role="alert" className="error">{settingsError(remove.error, 'Unable to delete account. Refresh and retry.')}</p>}
      {adoptConfirm && <div className="settings-confirm" role="group" aria-label={`Confirm web management for ${account.name}`}>
        <p>Manage <strong>{account.name}</strong> in the web console?</p><p>Web settings will take precedence over accounts.yaml. Existing inventory, account identity and history will be kept.</p>
        <div className="settings-actions"><button disabled={adopt.isPending} onClick={() => adopt.mutate()}>Confirm web management</button><button className="secondary" disabled={adopt.isPending} onClick={() => { setAdoptConfirm(false); adopt.reset(); }}>Cancel</button></div>
      </div>}
      {adopt.isError && <p role="alert" className="error">{settingsError(adopt.error, 'Unable to manage account in web. Refresh and retry.')}</p>}
      {confirm && <div className="settings-confirm" role="group" aria-label={`Confirm account change for ${account.name}`}>
        <p>{account.enabled ? 'Disable' : 'Enable'} <strong>{account.name}</strong>?</p>
        {account.enabled && <p>Scanning will stop. Existing inventory will be kept.</p>}
        <div className="settings-actions"><button disabled={activity.isPending} onClick={() => activity.mutate()}>Confirm change</button><button className="secondary" disabled={activity.isPending} onClick={() => { setConfirm(false); activity.reset(); }}>Cancel</button></div>
      </div>}
      {activity.isError && <p role="alert" className="error">{settingsError(activity.error, 'Unable to update account.', 'This account is managed by accounts.yaml. Refresh the list.')}</p>}
      {access.isPending && <p role="status">Checking account access…</p>}
      {access.data && <p role={access.data.ok ? 'status' : 'alert'} className={access.data.ok ? '' : 'error'}>{access.data.ok ? `Access OK · ${access.data.regions} regions` : access.data.error}</p>}
      {access.isError && <p role="alert" className="error">{settingsError(access.error, 'Unable to test access. Please try again.')}</p>}
    </td>
  </tr>;
}

export default function CloudAccounts() {
  const client = useQueryClient();
  const [editing, setEditing] = useState<AccountSummary | 'new' | null>(null);
  const [notice, setNotice] = useState('');
  const accounts = useQuery({ queryKey: ['accounts'], queryFn: async ({ signal }): Promise<AccountSummary[]> => (await apiFetch('/api/accounts', { signal })).json() });
  const capabilities = useQuery({ queryKey: ['account-capabilities'], queryFn: async ({ signal }): Promise<{ dedicated_credentials: boolean }> => (await apiFetch('/api/accounts/capabilities', { signal })).json() });
  async function refresh() {
    await Promise.all(['accounts', 'instance-facets', 'instances', 'instance', 'sync', 'load-balancers', 'load-balancer'].map(key => client.invalidateQueries({ queryKey: [key] })));
  }
  return <section className="settings-card cloud-accounts" aria-labelledby="accounts-title"><h2 id="accounts-title">Cloud accounts</h2>
    <p>Choose Runtime credentials, Assume Role or an account’s own Access Key. Existing file accounts can be moved to web management without deleting inventory.</p>
    <div className="settings-actions"><button onClick={() => { setNotice(''); setEditing('new'); }} disabled={editing !== null}>Add cloud account</button><button className="secondary" disabled={accounts.isFetching} onClick={() => void refresh()}>Refresh accounts</button></div>
    {accounts.isPending && <p role="status">Loading accounts…</p>}
    {accounts.isError && <p role="alert" className="error">Unable to {accounts.data ? 'refresh' : 'load'} accounts. <button onClick={() => void accounts.refetch()}>Retry accounts</button></p>}
    {Array.isArray(accounts.data) && <div className="settings-table-scroll"><table className="settings-table"><thead><tr>{['Provider', 'Name', 'Account alias', 'Account ID', 'Regions', 'Connection', 'Source', 'Status', 'Last success', 'Instances', 'Actions'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead>
      <tbody>{accounts.data.map(account => <AccountRow key={`${account.provider}/${account.account_id}`} account={account} editing={editing !== null} onChanged={refresh} onEdit={() => { setNotice(''); setEditing(account); }} />)}</tbody></table>
      {accounts.data.length === 0 && <p>No cloud accounts yet.</p>}
    </div>}
    {editing && <AccountForm dedicatedEnabled={capabilities.data?.dedicated_credentials ?? false} key={editing === 'new' ? 'new' : `${editing.provider}/${editing.account_id}`} account={editing === 'new' ? undefined : editing} onCancel={() => setEditing(null)} onSaved={() => { setEditing(null); setNotice('Account saved.'); void refresh(); }} />}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
