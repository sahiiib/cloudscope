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

export interface MFASetup {
  otpauth_uri: string;
  qr_svg: string;
}
export interface ManagedUser extends AuthUser {
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface SecurityRule {
  protocol?: string | null;
  port_range?: string | null;
  source?: string | null;
  destination?: string | null;
  description?: string | null;
  policy?: string | null;
  priority?: number | string | null;
  source_port_range?: string | null;
}
export interface SecurityGroup {
  id: string;
  name?: string | null;
  description?: string | null;
  inbound?: SecurityRule[] | null;
  outbound?: SecurityRule[] | null;
}
export interface NetworkSegment { id?: string | null; name?: string | null; cidr?: string | null }
export interface NetworkInterface {
  id: string;
  private_ips?: string[] | null;
  public_ip?: string | null;
  mac?: string | null;
  security_group_ids?: string[] | null;
}
export interface InstanceExtras {
  security_groups?: SecurityGroup[] | null;
  vpc?: NetworkSegment | null;
  subnet?: NetworkSegment | null;
  network_interfaces?: NetworkInterface[] | null;
  key_pair?: { name?: string | null } | null;
  iam_role?: string | null;
  image?: { id?: string | null; name?: string | null } | null;
  cpu?: number | null;
  memory_mib?: number | null;
  monitoring?: string | null;
}
export interface InstanceDetail extends InstanceSummary {
  zone: string | null;
  vpc_id: string | null;
  subnet_id: string | null;
  key_name: string | null;
  image_id: string | null;
  platform: string | null;
  provider_state: string;
  first_seen: string;
  details: InstanceExtras | null;
  raw: Record<string, unknown> | null;
}
