import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { ApiError, apiFetch } from '../api/client';
import { leaveApp } from './navigation';
import type { AuthUser, LogoutResult } from '../api/types';
import ThemePicker from '../appearance/ThemePicker';

export default function ProtectedLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: async (): Promise<AuthUser> => (await apiFetch('/api/auth/me', { redirectOnUnauthorized: false })).json() as Promise<AuthUser>,
    retry: false,
  });
  const logout = useMutation({
    mutationFn: async () => {
      try { return await (await apiFetch('/api/auth/logout', { method: 'POST' })).json() as LogoutResult; }
      catch (error) { if (!(error instanceof ApiError && error.status === 401)) throw error; }
    },
    onSuccess: result => {
      queryClient.clear();
      if (result?.logout_url) leaveApp(result.logout_url);
      else navigate('/login', { replace: true });
    },
  });
  if (me.isPending) return <main role="status">Checking your session…</main>;
  if (me.isError && !me.data) {
    if (me.error instanceof ApiError && me.error.status === 401) {
      return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
    }
    return <main><p role="alert">Unable to check your session.</p><button type="button" onClick={() => void me.refetch()}>Try again</button></main>;
  }
  return <div className="console-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <header className="topbar">
      <NavLink className="brand" to="/"><span className="brand-symbol" aria-hidden="true">C</span><span>Cloudscope<small>Cloud inventory</small></span></NavLink>
      <span className="nav-caption">Workspace</span>
      <nav aria-label="Main navigation">
        <NavLink to="/" end><span aria-hidden="true">&#9638;</span> Instances</NavLink>
        {me.data.is_admin && <NavLink to="/accounts"><span aria-hidden="true">&#9678;</span> Accounts</NavLink>}
        <NavLink to="/load-balancers">Load balancers</NavLink>
        <NavLink to="/elastic-ips">Elastic IPs</NavLink>
        <NavLink to="/nat-gateways">NAT gateways</NavLink>
        <NavLink to="/sync"><span aria-hidden="true">&#8635;</span> Sync</NavLink>
        <NavLink to="/settings"><span aria-hidden="true">&#9881;</span> Settings</NavLink>
      </nav>
      <div className="sidebar-footer"><ThemePicker /><details className="user-menu"><summary>{me.data.username}</summary>
        <div><span>{me.data.is_admin ? 'Administrator' : 'Member'}</span>
          <button type="button" onClick={() => logout.mutate()} disabled={logout.isPending}>{logout.isPending ? 'Signing out…' : 'Log out'}</button>
        </div>
      </details><p className="read-only-note">Read-only cloud access</p></div>
    </header>
    <main id="main-content" tabIndex={-1}>
      {logout.isError && <p role="alert" className="error">Unable to log out. Please try again.</p>}
      <Outlet context={me.data} />
    </main>
  </div>;
}
