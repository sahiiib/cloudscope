import { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { apiFetch } from '../api/client';
import type { MFASetup } from '../api/types';
import { settingsError } from './errors';

export default function MFASettings({ enabled, onChanged }: { enabled: boolean; onChanged: (enabled: boolean) => void }) {
  const [provisioning, setProvisioning] = useState<MFASetup | null>(null);
  const [notice, setNotice] = useState('');
  const payload = useRef<string | undefined>(undefined);
  useEffect(() => () => { payload.current = undefined; }, []);
  const setup = useMutation({
    gcTime: 0,
    mutationFn: async () => {
      // Keep provisioning data only in this mounted component, never the query/mutation cache.
      const result: MFASetup = await (await apiFetch('/api/auth/mfa/setup', { method: 'POST' })).json();
      setProvisioning(result);
    },
    onMutate: () => { setNotice(''); setProvisioning(null); },
  });
  const change = useMutation({
    gcTime: 0,
    mutationFn: async () => {
      const body = payload.current;
      payload.current = undefined;
      if (!body) throw new Error('No pending MFA change');
      await apiFetch(enabled ? '/api/auth/mfa/disable' : '/api/auth/mfa/enable', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body, redirectOnUnauthorized: false,
      });
    },
    onSuccess: () => {
      setProvisioning(null); setNotice(enabled ? 'MFA disabled.' : 'MFA enabled. Other sessions have been signed out.'); onChanged(!enabled);
    },
  });
  return <section className="settings-card" aria-labelledby="mfa-title"><h2 id="mfa-title">Authenticator MFA</h2>
    <p>MFA is <strong>{enabled ? 'enabled' : 'disabled'}</strong>.</p>
    {notice && <p role="status">{notice}</p>}
    {!enabled && !provisioning && <button disabled={setup.isPending} onClick={() => { change.reset(); setup.mutate(); }}>{setup.isPending ? 'Preparing…' : 'Set up MFA'}</button>}
    {setup.isError && <p role="alert" className="error">{settingsError(setup.error, 'Unable to prepare MFA. Please try again.')}</p>}
    {!enabled && provisioning && <div className="mfa-enrollment">
      <p>Scan this QR code with your authenticator, then enter a fresh six-digit code.</p>
      <img width={240} height={240} alt="Authenticator enrollment QR code" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(provisioning.qr_svg)}`} />
      <details><summary>Manual enrollment URI</summary><code className="mfa-uri">{provisioning.otpauth_uri}</code></details>
    </div>}
    {(enabled || provisioning) && <form key={String(enabled)} aria-label={enabled ? 'Disable MFA' : 'Confirm MFA'} onSubmit={event => {
      event.preventDefault();
      if (!change.isPending) {
        const fields = new FormData(event.currentTarget);
        payload.current = JSON.stringify(enabled ? { password: fields.get('password'), code: fields.get('code') } : { code: fields.get('code') });
        event.currentTarget.reset();
        change.mutate();
      }
    }}><fieldset disabled={change.isPending}>
      {enabled && <><p>Disabling MFA removes the authenticator and signs out your other sessions.</p>
        <label>MFA password<input name="password" type="password" autoComplete="current-password" required /></label></>}
      <label>Authenticator code<input name="code" autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" minLength={6} maxLength={6} required /></label>
      <button type="submit">{change.isPending ? 'Saving…' : enabled ? 'Disable MFA' : 'Confirm MFA'}</button>
      {!enabled && <button type="button" className="secondary" onClick={() => { setProvisioning(null); change.reset(); }}>Cancel setup</button>}
    </fieldset></form>}
    {change.isError && <p role="alert" className="error">{settingsError(change.error, 'Unable to update MFA. Please try again.')}</p>}
  </section>;
}
