import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { ApiError, apiFetch } from '../api/client';
import type { AuthUser } from '../api/types';

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
      try { await apiFetch('/api/auth/logout', { method: 'POST' }); }
      catch (error) { if (!(error instanceof ApiError && error.status === 401)) throw error; }
    },
    onSuccess: () => { queryClient.clear(); navigate('/login', { replace: true }); },
  });
  if (me.isPending) return <main role="status">Checking your session…</main>;
  if (me.isError) {
    if (me.error instanceof ApiError && me.error.status === 401) {
      return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
    }
    return <main><p role="alert">Unable to check your session.</p><button onClick={() => void me.refetch()}>Try again</button></main>;
  }
  return <>
    <header className="topbar">
      <NavLink className="brand" to="/">Cloudscope</NavLink>
      <nav aria-label="Main navigation">
        <NavLink to="/" end>Search</NavLink><NavLink to="/sync">Sync</NavLink><NavLink to="/settings">Settings</NavLink>
      </nav>
      <details className="user-menu"><summary>{me.data.username}</summary>
        <div><span>{me.data.is_admin ? 'Administrator' : 'Member'}</span>
          <button onClick={() => logout.mutate()} disabled={logout.isPending}>{logout.isPending ? 'Signing out…' : 'Log out'}</button>
        </div>
      </details>
    </header>
    {logout.isError && <p role="alert" className="error">Unable to log out. Please try again.</p>}
    <main><Outlet context={me.data} /></main>
  </>;
}
