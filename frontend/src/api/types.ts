/** Public authentication responses from docs/specs/api.md. */
export interface AuthUser {
  id: number;
  username: string;
  is_admin: boolean;
  mfa_enabled: boolean;
}

export interface LoginResult {
  mfa_required: boolean;
}

export interface SyncRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  trigger: 'schedule' | 'manual';
  status: 'running' | 'success' | 'partial' | 'failed';
  instances_seen: number;
}
export interface SyncResult {
  provider: 'aws' | 'alibaba';
  account_id: string;
  region: string;
  status: 'success' | 'error';
  instances_seen: number;
  error: string | null;
  duration_ms: number;
}
export interface SyncRunDetail extends SyncRun { results: SyncResult[] }
