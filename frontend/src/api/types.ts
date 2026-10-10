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
