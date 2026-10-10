import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useMutation } from '@tanstack/react-query';
import { apiFetch } from '../api/client';
import { settingsError } from './errors';

export default function PasswordSettings({ onSessionEnd }: { onSessionEnd: () => void }) {
  const form = useRef<HTMLFormElement>(null);
  const payload = useRef<string | undefined>(undefined);
  useEffect(() => () => { payload.current = undefined; }, []);
  const [validation, setValidation] = useState('');
  const change = useMutation({
    gcTime: 0,
    mutationFn: async () => {
      const body = payload.current;
      payload.current = undefined;
      if (!body) throw new Error('No pending password change');
      await apiFetch('/api/auth/password', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, redirectOnUnauthorized: false });
    },
    onSuccess: onSessionEnd,
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    if (String(fields.get('new_password')).length < 12) { setValidation('Use at least 12 characters.'); return; }
    if (fields.get('new_password') !== fields.get('confirm_password')) { setValidation('New passwords do not match.'); return; }
    setValidation('');
    if (!change.isPending) {
      payload.current = JSON.stringify({ current_password: fields.get('current_password'), new_password: fields.get('new_password') });
      event.currentTarget.reset();
      change.mutate();
    }
  }
  return <section className="settings-card" aria-labelledby="password-title"><h2 id="password-title">Change password</h2>
    <p>Changing your password signs out all sessions, including this one.</p>
    <form ref={form} onSubmit={submit} aria-label="Change password"><fieldset disabled={change.isPending}>
      <label>Current password<input name="current_password" type="password" autoComplete="current-password" required /></label>
      <label>New password<input name="new_password" type="password" autoComplete="new-password" minLength={12} required /></label>
      <label>Confirm new password<input name="confirm_password" type="password" autoComplete="new-password" minLength={12} required /></label>
      <button type="submit">{change.isPending ? 'Changing…' : 'Change password'}</button>
    </fieldset>
      {validation && <p className="error" role="alert">{validation}</p>}
      {change.isError && <p className="error" role="alert">{settingsError(change.error, 'Unable to change password. Please try again.')}</p>}
    </form>
  </section>;
}
