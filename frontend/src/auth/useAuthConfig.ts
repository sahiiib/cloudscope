import { useQuery } from '@tanstack/react-query';
import { apiFetch } from '../api/client';
import type { AuthConfig } from '../api/types';

export function useAuthConfig() {
  return useQuery({
    queryKey: ['auth', 'config'],
    queryFn: async (): Promise<AuthConfig> => (await apiFetch('/api/auth/config', { redirectOnUnauthorized: false })).json(),
    staleTime: 60_000,
    retry: false,
  });
}
