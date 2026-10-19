import { useAuthConfig } from './useAuthConfig';
import ThemePicker from '../appearance/ThemePicker';
import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useLocation, useNavigate } from 'react-router-dom';
import { ApiError, apiFetch } from '../api/client';
import type { AuthConfig, LoginResult } from '../api/types';

function destination(state: unknown): string {
  if (state && typeof state === 'object' && 'from' in state && typeof state.from === 'string') {
    const path = state.from;
    if (path.startsWith('/') && !path.startsWith('//') && !path.startsWith('/login') && !path.includes('\\')) return path;
  }
  return '/';
}

export default function Login() {
  const config = useAuthConfig();
  const [adminSignIn, setAdminSignIn] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [mfa, setMfa] = useState(false);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const login = useMutation({
    mutationFn: async (): Promise<LoginResult> => {
      const response = await apiFetch(mfa ? '/api/auth/mfa/verify-login' : '/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(mfa ? { code } : { username, password }),
      });
      return response.json() as Promise<LoginResult>;
    },
    onSuccess: (result) => {
      const publicConfig = queryClient.getQueryData<AuthConfig>(['auth', 'config']);
      queryClient.clear();
      if (publicConfig) queryClient.setQueryData(['auth', 'config'], publicConfig);
      if (result.mfa_required) setMfa(true);
      else navigate(destination(location.state), { replace: true });
    },
    onSettled: () => { setPassword(''); setCode(''); },
  });
  const error = login.error instanceof ApiError && login.error.status === 429
    ? 'Too many attempts. Please wait a minute and try again.'
    : login.error instanceof ApiError && login.error.status === 401
      ? mfa ? 'Invalid code or expired sign-in. Try a fresh code or sign in again.' : 'Invalid username or password.'
      : 'Unable to sign in. Please try again.';

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!login.isPending) login.mutate();
  }

  return (
    <main className="login-page">
      <div className="login-appearance"><ThemePicker /></div>
      <section className="login-card" aria-labelledby="login-title">
        <p className="brand">Cloudscope</p>
        <h1 id="login-title">{mfa ? 'Verify your sign-in' : 'Sign in'}</h1>
        <p>{mfa ? 'Enter the six-digit code from your authenticator.' : 'Your cloud inventory, in one place.'}</p>
        {new URLSearchParams(location.search).get('error') === 'not-authorized'
          ? <p role="alert" className="error">Not authorized. Ask your administrator for Cloudscope access.</p>
          : new URLSearchParams(location.search).has('error') && <p role="alert" className="error">Unable to sign in with Keycloak. Please try again.</p>}
        {config.isPending && <p role="status">Loading sign-in options…</p>}
        {config.isError && <p role="alert">Unable to load sign-in options. <button onClick={() => void config.refetch()}>Try again</button></p>}
        {config.data?.sso.enabled && !mfa && <div className="sso-sign-in">
          <a className="sso-button" href={`/api/auth/oidc/login?${new URLSearchParams({ next: destination(location.state) })}`}>{config.data.sso.label}</a>
          {!adminSignIn && <a href="#admin-sign-in" onClick={event => { event.preventDefault(); setAdminSignIn(true); }}>Admin sign-in</a>}
        </div>}
        {(mfa || (config.data?.local_login && (!config.data.sso.enabled || adminSignIn))) && <form id="admin-sign-in" onSubmit={submit}>
          {mfa ? <label>Authenticator code
            <input key="code" autoFocus value={code} onChange={(e) => setCode(e.target.value)}
              autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" minLength={6} maxLength={6} required />
          </label> : <>
            <label>Username<input autoFocus value={username} onChange={(e) => setUsername(e.target.value)}
              autoComplete="username" maxLength={256} required /></label>
            <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password" required /></label>
          </>}
          {login.isError && <p role="alert" className="error">{error}</p>}
          <button type="submit" disabled={login.isPending}>{login.isPending ? 'Signing in…' : mfa ? 'Verify' : 'Sign in'}</button>
          {mfa && <button type="button" className="secondary" disabled={login.isPending}
            onClick={() => { setMfa(false); setCode(''); login.reset(); }}>Back to sign in</button>}
        </form>}
      </section>
    </main>
  );
}
