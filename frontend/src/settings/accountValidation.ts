import { ApiError } from '../api/client';
import type { AccountInput } from '../api/types';

export type AccountErrors = Partial<Record<keyof AccountInput | 'form', string>>;
// JavaScript's $ also matches before a final newline; require the entire value.
function matches(pattern: RegExp, value: string) { return pattern.exec(value)?.[0] === value; }

export function validateAccount(account: AccountInput): AccountErrors {
  const errors: AccountErrors = {};
  if (!['aws', 'alibaba'].includes(account.provider)) errors.provider = 'Choose AWS or Alibaba.';
  const digits = account.provider === 'aws' ? 12 : 16;
  if (!matches(new RegExp(`^[0-9]{${digits}}$`), account.account_id)) errors.account_id = `Use exactly ${digits} digits.`;
  if (![...account.name].length || [...account.name].length > 64 || account.name !== account.name.trim() || /\p{C}/u.test(account.name)) errors.name = 'Use 1–64 characters without surrounding whitespace or controls.';
  if (account.regions !== 'all' && (!account.regions.length || new Set(account.regions).size !== account.regions.length || account.regions.some(region => !matches(/^[a-z0-9-]{2,32}$/, region)))) errors.regions = 'Use all or a comma-separated list of unique region IDs.';
  if (account.excluded_regions && (account.excluded_regions.length > 64 || new Set(account.excluded_regions).size !== account.excluded_regions.length || account.excluded_regions.some(region => !matches(/^[a-z0-9-]{2,32}$/, region)))) errors.excluded_regions = 'Use up to 64 unique region IDs.';
  if (account.role_arn !== null) {
    const prefix = account.provider === 'aws' ? 'arn:aws:iam::' : 'acs:ram::';
    const expected = `${prefix}${account.account_id}:role/`;
    if (!account.role_arn.startsWith(expected) || !matches(/^[A-Za-z0-9_+=,.@/-]+$/, account.role_arn.slice(expected.length))) errors.role_arn = 'Role must match the provider and account ID.';
  }
  if (account.external_id !== null && (account.provider !== 'aws' || !matches(/^[\w+=,.@:/-]{2,1224}$/, account.external_id))) errors.external_id = 'External ID is AWS-only; use 2–1224 allowed characters.';
  if (typeof account.enabled !== 'boolean') errors.enabled = 'Choose enabled or disabled.';
  return errors;
}

export function accountErrors(error: unknown, editing: boolean): AccountErrors {
  if (error instanceof ApiError) {
    if (error.status === 409) return { account_id: typeof error.detail === 'string' ? error.detail : editing ? 'Managed by accounts.yaml; refresh the account list.' : 'This provider and account ID already exist.' };
    if (error.status === 403) return { form: 'You no longer have permission to manage accounts. Reload the page to refresh your access.' };
    if (error.status === 422 && Array.isArray(error.detail)) {
      const errors: AccountErrors = {};
      const details: unknown[] = error.detail;
      for (const item of details) {
        if (!item || typeof item !== 'object' || !('loc' in item) || !('msg' in item) || !Array.isArray(item.loc) || typeof item.msg !== 'string') continue;
        const field: unknown = item.loc[1];
        if (typeof field === 'string' && ['provider', 'account_id', 'name', 'regions', 'excluded_regions', 'role_arn', 'external_id', 'enabled'].includes(field)) errors[field as keyof AccountInput] = item.msg;
        else errors.form = 'Check the account fields and try again.';
      }
      if (Object.keys(errors).length) return errors;
    }
    if (error.status === 422) return { form: typeof error.detail === 'string' && error.detail.startsWith('Access validation failed:') ? error.detail : 'Check the account fields and try again.' };
  }
  return { form: 'Unable to save account. Please try again.' };
}
