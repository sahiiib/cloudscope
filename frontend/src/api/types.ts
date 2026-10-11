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

export interface MFASetup {
  otpauth_uri: string;
  qr_svg: string;
}
export interface ManagedUser extends AuthUser {
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}
