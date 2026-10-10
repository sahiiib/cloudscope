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

export interface InstanceSummary {
  provider: 'aws' | 'alibaba';
  account_id: string;
  account_name: string;
  region: string;
  instance_id: string;
  name: string | null;
  state: string;
  instance_type: string;
  private_ips: string[];
  public_ips: string[];
  tags: Record<string, string>;
  launch_time: string | null;
  last_observed: string;
  present: boolean;
}
export interface InstancePage {
  items: InstanceSummary[];
  total: number;
  page: number;
  page_size: number;
}
export interface Facet { value: string; count: number }
export interface InstanceFacets {
  providers: Facet[];
  accounts: Facet[];
  regions: Facet[];
  states: Facet[];
}
export interface AccountSummary {
  provider: 'aws' | 'alibaba';
  account_id: string;
  name: string;
  enabled: boolean;
  last_success_at: string | null;
  instance_count: number;
}
