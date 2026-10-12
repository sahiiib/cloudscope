import { useId, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { apiFetch } from '../api/client';
import type { AccountInput, AccountSummary } from '../api/types';
import { accountErrors, validateAccount, type AccountErrors } from './accountValidation';

export default function AccountForm({ account, onSaved, onCancel }: {
  account?: AccountSummary; onSaved: () => void; onCancel: () => void;
}) {
  const id = useId();
  const [values, setValues] = useState<AccountInput>(() => account ?? {
    provider: 'aws', account_id: '', name: '', regions: 'all', role_arn: null, external_id: null, enabled: true,
  });
  const [regions, setRegions] = useState(account?.regions === 'all' || !account ? 'all' : account.regions.join(', '));
  const [errors, setErrors] = useState<AccountErrors>({});
  const save = useMutation({
    mutationFn: async (input: AccountInput) => {
      const body = account ? { name: input.name, regions: input.regions, role_arn: input.role_arn, external_id: input.external_id } : input;
      await apiFetch(account ? `/api/accounts/${account.provider}/${account.account_id}` : '/api/accounts', {
        method: account ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
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
    const input: AccountInput = { ...values, regions: regions === 'all' ? 'all' : regions.split(',').map(region => region.trim()) };
    // Only input fields go to the API, never source/count/timestamps from a row.
    const body: AccountInput = { provider: input.provider, account_id: input.account_id, name: input.name, regions: input.regions, role_arn: input.role_arn, external_id: input.external_id, enabled: input.enabled };
    const invalid = validateAccount(body); setErrors(invalid);
    if (!Object.keys(invalid).length && !save.isPending) save.mutate(body);
  }}><h3>{account ? `Edit ${account.name}` : 'Add cloud account'}</h3>
    <fieldset disabled={save.isPending}>
      <label>Provider<select value={values.provider} disabled={!!account} {...accessibility('provider')} onChange={event => setValues({ ...values, provider: event.target.value as AccountInput['provider'], external_id: null })}>
        <option value="aws">AWS</option><option value="alibaba">Alibaba</option>
      </select>{fieldError('provider')}</label>
      <label>Account ID<input value={values.account_id} readOnly={!!account} inputMode="numeric" {...accessibility('account_id')} onChange={event => setValues({ ...values, account_id: event.target.value })} />{fieldError('account_id')}</label>
      <label>Name<input value={values.name} {...accessibility('name')} onChange={event => setValues({ ...values, name: event.target.value })} />{fieldError('name')}</label>
      <label>Regions<input value={regions} {...accessibility('regions')} onChange={event => setRegions(event.target.value)} />{fieldError('regions')}</label>
      <small>Enter all or comma-separated region IDs, for example eu-central-1, us-east-1.</small>
      <label>Role ARN (optional)<input value={values.role_arn ?? ''} {...accessibility('role_arn')} onChange={event => setValues({ ...values, role_arn: event.target.value || null })} />{fieldError('role_arn')}</label>
      <small>Leave blank to use the collector's base credentials.</small>
      {values.provider === 'aws' && <label>External ID (optional)<input value={values.external_id ?? ''} {...accessibility('external_id')} onChange={event => setValues({ ...values, external_id: event.target.value || null })} />{fieldError('external_id')}</label>}
      {!account && <label className="settings-check"><input type="checkbox" checked={values.enabled} onChange={event => setValues({ ...values, enabled: event.target.checked })} />Enabled{fieldError('enabled')}</label>}
      <div className="settings-actions"><button type="submit">{save.isPending ? 'Saving…' : account ? 'Save account' : 'Add account'}</button><button type="button" className="secondary" onClick={onCancel}>Cancel</button></div>
    </fieldset>
    {errors.form && <p role="alert" className="error">{errors.form}</p>}
  </form>;
}
