import { fireEvent, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { ApiError } from '../api/client';
import type { AccountSummary } from '../api/types';
import { fetchApi, renderSettings, response } from '../test/settings';
import AccountForm from './AccountForm';

function fill() {
  fireEvent.change(screen.getByLabelText('Account ID'), { target: { value: '111111111111' } });
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Test' } });
}
test('creates a validated account with explicit defaults and selected regions', async () => {
  fetchApi.mockResolvedValue(response({}));
  const saved = vi.fn(); renderSettings(<AccountForm onSaved={saved} onCancel={vi.fn()} />);
  fill();
  fireEvent.change(screen.getByLabelText('Regions'), { target: { value: 'eu-central-1, us-east-1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(fetchApi).toHaveBeenCalledWith('/api/accounts', expect.objectContaining({ method: 'POST', body: JSON.stringify({ provider: 'aws', account_id: '111111111111', name: 'Test', regions: ['eu-central-1', 'us-east-1'], excluded_regions: [], role_arn: null, external_id: null, enabled: true, connection_mode: 'runtime' }) }));
});
test.each([422, 409])('shows server %s beside its field, preserving the form', async status => {
  const detail = status === 422 ? [{ loc: ['body', 'role_arn'], msg: 'Role is invalid', type: 'value_error' }] : 'Account already exists';
  fetchApi.mockRejectedValue(new ApiError(status, detail));
  renderSettings(<AccountForm onSaved={vi.fn()} onCancel={vi.fn()} />);
  fill();
  if (status === 422) {
    fireEvent.change(screen.getByLabelText('Connection method'), { target: { value: 'role' } });
    fireEvent.change(screen.getByLabelText('Role ARN'), { target: { value: 'arn:aws:iam::111111111111:role/test' } });
  }
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  const alert = await screen.findByRole('alert');
  expect(alert).toHaveTextContent(status === 422 ? 'Role is invalid' : 'Account already exists');
  const field = screen.getByRole('textbox', { name: status === 422 ? /^Role ARN/ : /^Account ID/ });
  expect(field).toHaveAttribute('aria-invalid', 'true');
  expect(field).toHaveAttribute('aria-describedby', alert.id);
  expect(screen.getByLabelText('Name')).toHaveValue('Test');
});
test('edits UI fields, clearing optional values without sending immutable or response fields', async () => {
  const account: AccountSummary = { provider: 'aws', account_id: '111111111111', name: 'Test', regions: 'all', role_arn: 'arn:aws:iam::111111111111:role/test', external_id: 'test-id', enabled: true, source: 'ui', cloud_alias: 'demo-alias', last_success_at: null, instance_count: 2 };
  fetchApi.mockResolvedValue(response({}));
  const saved = vi.fn(); renderSettings(<AccountForm account={account} onSaved={saved} onCancel={vi.fn()} />);
  expect(screen.getByLabelText('Provider')).toBeDisabled();
  expect(screen.getByLabelText('Account ID')).toHaveAttribute('readonly');
  expect(screen.queryByLabelText('Enabled')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Renamed' } });
  for (const field of ['Role ARN', 'External ID (optional)']) fireEvent.change(screen.getByLabelText(field), { target: { value: '' } });
  fireEvent.change(screen.getByLabelText('Connection method'), { target: { value: 'runtime' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save account' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(fetchApi).toHaveBeenCalledWith('/api/accounts/aws/111111111111', expect.objectContaining({ method: 'PATCH', body: '{"name":"Renamed","regions":"all","excluded_regions":[],"role_arn":null,"external_id":null,"connection_mode":"runtime"}' }));
});
test('rejects invalid input locally and supports Alibaba IDs without external ID', async () => {
  fetchApi.mockResolvedValue(response({}));
  const saved = vi.fn(); renderSettings(<AccountForm onSaved={saved} onCancel={vi.fn()} />);
  fill(); fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'alibaba' } });
  expect(screen.queryByLabelText('External ID (optional)')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  expect(screen.getByRole('alert')).toHaveTextContent('16 digits');
  expect(fetchApi).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('textbox', { name: /^Account ID/ }), { target: { value: '1111111111111111' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
});

test('trims the all-region sentinel before building the API payload', async () => {
  fetchApi.mockResolvedValue(response({}));
  const saved = vi.fn(); renderSettings(<AccountForm onSaved={saved} onCancel={vi.fn()} />);
  fill();
  fireEvent.change(screen.getByLabelText('Regions'), { target: { value: ' all ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(JSON.parse(String(fetchApi.mock.calls[0][1]?.body)).regions).toBe('all');
});

test('tests unsaved settings and saves region checklist exclusions', async () => {
  fetchApi.mockImplementation(async path => response(path.endsWith('/test-connection') ? { ok: true, regions: ['us-east-1', 'us-west-2'] } : {}));
  const saved = vi.fn();
  renderSettings(<AccountForm onSaved={saved} onCancel={vi.fn()} />);
  fill(); fireEvent.click(screen.getByRole('button', { name: 'Select regions' }));
  expect(await screen.findByText('Connection OK')).toBeInTheDocument();
  expect(saved).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Scan us-west-2' }));
  fireEvent.click(screen.getByRole('button', { name: 'Add account' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(JSON.parse(String(fetchApi.mock.calls.find(([path]) => path === '/api/accounts')?.[1]?.body)).excluded_regions).toEqual(['us-west-2']);
});

test('pre-save dedicated test clears key inputs without putting keys in caches', async () => {
  fetchApi.mockResolvedValue(response({ ok: true, regions: ['us-east-1'] }));
  const client = renderSettings(<AccountForm dedicatedEnabled onSaved={vi.fn()} onCancel={vi.fn()} />);
  fill();
  fireEvent.change(screen.getByLabelText('Access Key ID'), { target: { value: 'fixture-key' } });
  fireEvent.change(screen.getByLabelText('Secret Access Key'), { target: { value: 'fixture-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Select regions' }));
  await screen.findByText('Connection OK');
  expect(screen.getByLabelText('Access Key ID')).toHaveValue('');
  expect(screen.getByLabelText('Secret Access Key')).toHaveValue('');
  expect(fetchApi.mock.calls).toHaveLength(1);
  expect(fetchApi.mock.calls[0][0]).toBe('/api/accounts/test-connection');
  expect(JSON.parse(String(fetchApi.mock.calls[0][1]?.body)).credentials.secret_access_key).toBe('fixture-secret');
  expect(JSON.stringify(client.getMutationCache().getAll().map(item => item.state))).not.toContain('fixture-');
  expect(JSON.stringify(client.getQueryCache().getAll().map(item => item.state))).not.toContain('fixture-');
});

test('failed pre-save check displays sanitized error and does not save', async () => {
  fetchApi.mockResolvedValue(response({ ok: false, error: 'Region discovery failed: AccessDenied' }));
  const saved = vi.fn(); renderSettings(<AccountForm onSaved={saved} onCancel={vi.fn()} />);
  fill(); fireEvent.click(screen.getByRole('button', { name: 'Select regions' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('AccessDenied');
  expect(saved).not.toHaveBeenCalled();
});


test('retyping dedicated keys retains the discovered checklist and selected exclusions', async () => {
  fetchApi.mockResolvedValue(response({ ok: true, regions: ['us-east-1', 'us-west-2'] }));
  renderSettings(<AccountForm dedicatedEnabled onSaved={vi.fn()} onCancel={vi.fn()} />);
  fill();
  fireEvent.change(screen.getByLabelText('Access Key ID'), { target: { value: 'fixture-key' } });
  fireEvent.change(screen.getByLabelText('Secret Access Key'), { target: { value: 'fixture-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Select regions' }));
  await screen.findByRole('checkbox', { name: 'Scan us-west-2' });
  for (const label of ['Access Key ID', 'Secret Access Key', 'Session Token (optional)']) {
    fireEvent.change(screen.getByLabelText(label), { target: { value: 'fixture-retyped' } });
    expect(screen.getByRole('checkbox', { name: 'Scan us-west-2' })).toBeInTheDocument();
  }
  fireEvent.click(screen.getByRole('checkbox', { name: 'Scan us-west-2' }));
  expect(screen.getByRole('checkbox', { name: 'Scan us-west-2' })).not.toBeChecked();
  expect(screen.getByText('Connection OK')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Regions'), { target: { value: 'us-east-1' } });
  expect(screen.queryByText('Connection OK')).not.toBeInTheDocument();
  expect(screen.queryByRole('checkbox', { name: 'Scan us-east-1' })).not.toBeInTheDocument();
});
test('always shows the excluded regions section with a hint before the first test', () => {
  renderSettings(<AccountForm onSaved={vi.fn()} onCancel={vi.fn()} />);
  const group = screen.getByRole('group', { name: 'Regions to scan' });
  expect(group).toHaveTextContent('Click Select regions to discover this account’s regions');
});

const savedDedicated: AccountSummary = { provider: 'aws', account_id: '111111111111', name: 'Saved', regions: 'all', role_arn: null, external_id: null, enabled: true, source: 'ui', cloud_alias: null, last_success_at: '2026-01-01T00:00:00Z', instance_count: 12, connection_mode: 'dedicated', credentials_configured: true, configuration_version: 3, excluded_regions: ['us-west-2'] };
const knownRegions = [
  { region: 'eu-central-1', instances: 12, load_balancers: 3, excluded: false },
  { region: 'us-west-2', instances: 0, load_balancers: 0, excluded: true },
];

test('edit loads counts immediately and previews with saved keys, merging new regions without losing choices', async () => {
  fetchApi.mockImplementation(async (path, options) => response(path.endsWith('/regions') ? { regions: knownRegions } : options?.method === 'POST' ? { ok: true, regions: ['eu-central-1', 'us-west-2', 'ap-south-1'] } : {}));
  const saved = vi.fn(); renderSettings(<AccountForm account={savedDedicated} dedicatedEnabled onSaved={saved} onCancel={vi.fn()} />);
  expect(await screen.findByText('eu-central-1 · 12 instances · 3 load balancers')).toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: 'Scan eu-central-1' })).toBeChecked();
  expect(screen.getByRole('checkbox', { name: 'Scan us-west-2' })).not.toBeChecked();
  expect(fetchApi.mock.calls.every(([, options]) => options?.method !== 'POST')).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Select regions' }));
  await screen.findByText('Connection OK');
  const preview = fetchApi.mock.calls.find(([path]) => path.endsWith('/test-connection'))!;
  expect(preview[0]).toBe('/api/accounts/aws/111111111111/test-connection');
  expect(JSON.parse(String(preview[1]?.body))).not.toHaveProperty('credentials');
  expect(screen.queryByText(/Re-enter them/)).not.toBeInTheDocument();
  expect(screen.getByText('ap-south-1 · 0 instances · 0 load balancers')).toBeInTheDocument();
  expect(screen.getByText('eu-central-1 · 12 instances · 3 load balancers')).toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: 'Scan us-west-2' })).not.toBeChecked();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Scan eu-central-1' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save account' }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  const patch = fetchApi.mock.calls.find(([, options]) => options?.method === 'PATCH')!;
  expect(JSON.parse(String(patch[1]?.body))).toMatchObject({ excluded_regions: ['us-west-2', 'eu-central-1'], expected_version: 3 });
});

test('unticking every region blocks saving until one region is selected', async () => {
  fetchApi.mockImplementation(async () => response({ regions: knownRegions }));
  renderSettings(<AccountForm account={savedDedicated} dedicatedEnabled onSaved={vi.fn()} onCancel={vi.fn()} />);
  await screen.findByText('eu-central-1 · 12 instances · 3 load balancers');
  fireEvent.click(screen.getByRole('checkbox', { name: 'Scan eu-central-1' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Keep at least one region');
  expect(screen.getByRole('button', { name: 'Save account' })).toBeDisabled();
  fireEvent.submit(screen.getByRole('form', { name: 'Edit cloud account' }));
  expect(fetchApi.mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(false);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Scan us-west-2' }));
  expect(screen.queryByText('Keep at least one region')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Save account' })).toBeEnabled();
});

test('edit preview uses new keys when entered and rejects incomplete pairs', async () => {
  fetchApi.mockImplementation(async path => response(path.endsWith('/regions') ? { regions: knownRegions } : { ok: true, regions: ['eu-central-1'] }));
  renderSettings(<AccountForm account={savedDedicated} dedicatedEnabled onSaved={vi.fn()} onCancel={vi.fn()} />);
  await screen.findByText('eu-central-1 · 12 instances · 3 load balancers');
  fireEvent.change(screen.getByLabelText('Access Key ID'), { target: { value: 'fixture-new-key' } });
  fireEvent.click(screen.getByRole('button', { name: 'Select regions' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Enter both');
  expect(fetchApi.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(false);
  fireEvent.change(screen.getByLabelText('Secret Access Key'), { target: { value: 'fixture-new-secret' } });
  fireEvent.click(screen.getByRole('button', { name: 'Select regions' }));
  await screen.findByText('Connection OK');
  const call = fetchApi.mock.calls.find(([, options]) => options?.method === 'POST')!;
  expect(JSON.parse(String(call[1]?.body)).credentials).toEqual({ access_key_id: 'fixture-new-key', secret_access_key: 'fixture-new-secret' });
});

test('failed known-region load retries without testing or writing the connection', async () => {
  let fail = true;
  fetchApi.mockImplementation(async path => {
    if (path.endsWith('/regions') && fail) throw new ApiError(503);
    return response({ regions: knownRegions });
  });
  renderSettings(<AccountForm account={savedDedicated} dedicatedEnabled onSaved={vi.fn()} onCancel={vi.fn()} />);
  expect(await screen.findByRole('button', { name: 'Retry regions' })).toBeInTheDocument();
  fail = false;
  fireEvent.click(screen.getByRole('button', { name: 'Retry regions' }));
  expect(await screen.findByText('eu-central-1 · 12 instances · 3 load balancers')).toBeInTheDocument();
  expect(fetchApi.mock.calls.every(([, options]) => !options?.method)).toBe(true);
});
