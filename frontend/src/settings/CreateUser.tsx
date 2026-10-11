import { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { apiFetch } from '../api/client';
import { settingsError } from './errors';

export default function CreateUser({ onCreated }: { onCreated: () => void }) {
  const form = useRef<HTMLFormElement>(null);
  const payload = useRef<string | undefined>(undefined);
  useEffect(() => () => { payload.current = undefined; }, []);
  const [validation, setValidation] = useState('');
  const create = useMutation({
    gcTime: 0,
    mutationFn: async () => {
      const body = payload.current;
      payload.current = undefined;
      if (!body) throw new Error('No pending user creation');
      await apiFetch('/api/users', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body });
    },
    onSuccess: () => { form.current?.reset(); onCreated(); },
  });
  return <form ref={form} aria-label="Create user" onSubmit={event => {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const username = String(fields.get('username'));
    if (!username.trim() || username !== username.trim()) { setValidation('Username must not be blank or have surrounding spaces.'); return; }
    if (String(fields.get('password')).length < 12) { setValidation('Use at least 12 characters.'); return; }
    setValidation('');
    if (!create.isPending) {
      payload.current = JSON.stringify({ username, password: fields.get('password'), is_admin: fields.get('is_admin') === 'on' });
      const password = event.currentTarget.elements.namedItem('password');
      if (password instanceof HTMLInputElement) password.value = '';
      create.mutate();
    }
  }}><h3>Create user</h3><fieldset disabled={create.isPending}>
    <label>New username<input name="username" autoComplete="off" maxLength={256} required /></label>
    <label>Initial password<input name="password" type="password" autoComplete="new-password" minLength={12} required /></label>
    <label className="settings-check"><input name="is_admin" type="checkbox" />Administrator</label>
    <button type="submit">{create.isPending ? 'Creating…' : 'Create user'}</button>
  </fieldset>
    {validation && <p role="alert" className="error">{validation}</p>}
    {create.isError && <p role="alert" className="error">{settingsError(create.error, 'Unable to create user.', 'That username already exists.')}</p>}
    {create.isSuccess && <p role="status">User created.</p>}
  </form>;
}
