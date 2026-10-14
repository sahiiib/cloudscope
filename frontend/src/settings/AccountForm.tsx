import { useEffect, useId, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { apiFetch } from '../api/client';
import type { AccountInput, AccountSummary } from '../api/types';
import { accountErrors, validateAccount, type AccountErrors } from './accountValidation';

export default function AccountForm({ account, onSaved, onCancel, dedicatedEnabled = false }: {
  account?: AccountSummary; onSaved: () => void; onCancel: () => void; dedicatedEnabled?: boolean;
}) {
  const id = useId();
  const [values, setValues] = useState<AccountInput>(() => account ?? {
    provider: 'aws', account_id: '', name: '', regions: 'all', role_arn: null, external_id: null, enabled: true,
  });
  const [regions, setRegions] = useState(account?.regions === 'all' || !account ? 'all' : account.regions.join(', '));
  const [errors, setErrors] = useState<AccountErrors>({});
  const [method, setMethod] = useState<'runtime' | 'role' | 'dedicated'>(account?.connection_mode === 'dedicated' ? 'dedicated' : account?.role_arn ? 'role' : 'runtime');
  const pendingKeys = useRef<Record<string, string> | null>(null);
  useEffect(() => () => { pendingKeys.current = null; }, []);
  const save = useMutation({
    mutationFn: async (input: AccountInput) => {
      const keys = pendingKeys.current; pendingKeys.current = null;
      const body = account ? { name: input.name, regions: input.regions, role_arn: input.role_arn, external_id: input.external_id, connection_mode: input.connection_mode, expected_version: account.configuration_version } : input;
      await apiFetch(account ? `/api/accounts/${account.provider}/${account.account_id}` : '/api/accounts', {
        method: account ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, ...(keys ? { credentials: keys } : {}) }),
      });
    },
    onSuccess: onSaved,
    onError: error => setErrors(accountErrors(error, !!account)),
  });
  function fieldError(field: keyof AccountInput) {
    return errors[field] && <span id={`${id}-${field}-error`} role="alert" className="error">{errors[field]}</span>;
  }
  function accessibility(field: keyof AccountInput) {
    return { 'aria-invalid': !!errors[field], 'aria-describedby': errors[field] ? `${id}-${field}-error` : undefined };
  }
  return <form className="account-form" aria-label={account ? 'Edit cloud account' : 'Add cloud account'} noValidate onSubmit={event => {
    event.preventDefault();
    const input: AccountInput = { ...values, regions: regions.trim() === 'all' ? 'all' : regions.split(',').map(region => region.trim()) };
    // Only input fields go to the API, never source/count/timestamps from a row.
    const body: AccountInput = { provider: input.provider, account_id: input.account_id, name: input.name, regions: input.regions, role_arn: method === 'role' ? input.role_arn : null, external_id: method === 'role' ? input.external_id : null, enabled: input.enabled, connection_mode: method === 'dedicated' ? 'dedicated' : 'runtime' };
    const invalid = validateAccount(body); setErrors(invalid);
    if (method === 'role' && !body.role_arn) invalid.role_arn = 'Enter the role ARN.';
    if (method === 'dedicated') {
      const form = event.currentTarget;
      const read = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | null)?.value ?? '';
      const keyId = read('access_key_id'); const secret = read('secret_access_key'); const token = read('session_token');
      if ((keyId || secret || token) && (!keyId || !secret)) invalid.form = 'Enter both the access key ID and secret access key.';
      else if (!keyId && !account?.credentials_configured) invalid.form = 'Enter the access key ID and secret access key.';
      else if (keyId && secret) pendingKeys.current = { access_key_id: keyId, secret_access_key: secret, ...(token ? { session_token: token } : {}) };
      for (const name of ['access_key_id', 'secret_access_key', 'session_token']) { const field = form.elements.namedItem(name) as HTMLInputElement | null; if (field) field.value = ''; }
    }
    setErrors(invalid);
    if (!Object.keys(invalid).length && !save.isPending) save.mutate(body); else pendingKeys.current = null;
  }}><h3>{account ? `Edit ${account.name}` : 'Add cloud account'}</h3>
    <fieldset disabled={save.isPending}>
      <label>Provider<select value={values.provider} disabled={!!account} {...accessibility('provider')} onChange={event => setValues({ ...values, provider: event.target.value as AccountInput['provider'], external_id: null })}>
        <option value="aws">AWS</option><option value="alibaba">Alibaba</option>
      </select>{fieldError('provider')}</label>
      <label>Account ID<input value={values.account_id} readOnly={!!account} inputMode="numeric" {...accessibility('account_id')} onChange={event => setValues({ ...values, account_id: event.target.value })} />{fieldError('account_id')}</label>
      <label>Name<input value={values.name} {...accessibility('name')} onChange={event => setValues({ ...values, name: event.target.value })} />{fieldError('name')}</label>
      <label>Regions<input value={regions} {...accessibility('regions')} onChange={event => setRegions(event.target.value)} />{fieldError('regions')}</label>
      <small>Enter all or comma-separated region IDs, for example eu-central-1, us-east-1.</small>
      <label>Connection method<select value={method} onChange={event => { pendingKeys.current = null; setMethod(event.target.value as typeof method); }}>
        <option value="runtime">Runtime credentials</option><option value="role">Assume Role</option><option value="dedicated" disabled={!dedicatedEnabled}>Dedicated Access Key</option>
      </select></label>
      {method === 'runtime' && <p>Use the credentials configured on the server.</p>}
      {!dedicatedEnabled && <small>Dedicated Access Keys must be enabled by the operator.</small>}
      {method === 'role' && <>
        <label>Role ARN<input value={values.role_arn ?? ''} {...accessibility('role_arn')} onChange={event => setValues({ ...values, role_arn: event.target.value || null })} />{fieldError('role_arn')}</label>
        {values.provider === 'aws' && <label>External ID (optional)<input value={values.external_id ?? ''} {...accessibility('external_id')} onChange={event => setValues({ ...values, external_id: event.target.value || null })} />{fieldError('external_id')}</label>}
      </>}
      {method === 'dedicated' && <div className="credential-fields" key={values.provider}>
        <p>{account?.credentials_configured ? 'Keys are configured. Leave both fields blank to keep them, or enter a new pair to rotate.' : 'Enter this account’s own read-only key pair.'} Keys are never shown again. Account identity and access are checked before saving.</p>
        <label>Access Key ID<input name="access_key_id" type="password" autoComplete="off" maxLength={256} /></label>
        <label>{values.provider === 'alibaba' ? 'Access Key Secret' : 'Secret Access Key'}<input name="secret_access_key" type="password" autoComplete="new-password" maxLength={4096} /></label>
        {values.provider === 'aws' && <label>Session Token (optional)<input name="session_token" type="password" autoComplete="off" maxLength={8192} /></label>}
      </div>}
      {!account && <label className="settings-check"><input type="checkbox" checked={values.enabled} onChange={event => setValues({ ...values, enabled: event.target.checked })} />Enabled{fieldError('enabled')}</label>}
      <div className="settings-actions"><button type="submit">{save.isPending ? 'Saving…' : account ? 'Save account' : 'Add account'}</button><button type="button" className="secondary" onClick={onCancel}>Cancel</button></div>
    </fieldset>
    {errors.form && <p role="alert" className="error">{errors.form}</p>}
  </form>;
}
