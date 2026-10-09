import { describe, expect, test, vi } from 'vitest';
import { ApiError, apiFetch } from './client';

describe('apiFetch', () => {
  test('preserves request options while enforcing the CSRF header and credentials', async () => {
    const response = new Response('{"mfa_required":false}', { status: 200 });
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response);
    vi.stubGlobal('fetch', fetchMock);

    const result = await apiFetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'other' },
      body: '{"username":"test-user"}',
      credentials: 'omit',
    });

    expect(result).toBe(response);
    const [path, options] = fetchMock.mock.calls[0];
    expect(path).toBe('/api/auth/login');
    expect(options).toMatchObject({
      method: 'POST',
      body: '{"username":"test-user"}',
      credentials: 'same-origin',
    });
    const headers = new Headers(options?.headers);
    expect(headers.get('X-Requested-With')).toBe('cloudscope');
    expect(headers.get('Content-Type')).toBe('application/json');
  });

  test('supports requests without options and empty successful responses', async () => {
    const response = new Response(null, { status: 204 });
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(response);
    vi.stubGlobal('fetch', fetchMock);
    expect(await apiFetch('/api/auth/logout')).toBe(response);
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('X-Requested-With')).toBe('cloudscope');
  });

  test('redirects unauthorized requests to login and rejects the request', async () => {
    const assign = vi.fn();
    vi.stubGlobal('location', { assign, pathname: '/' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    await expect(apiFetch('/api/auth/me')).rejects.toMatchObject({ status: 401 });
    expect(assign).toHaveBeenCalledWith('/login');
  });

  test.each(['/api/auth/login', '/api/auth/mfa/verify-login'] as const)(
    'keeps a 401 from %s available for inline errors without redirecting',
    async (path) => {
      const assign = vi.fn();
      vi.stubGlobal('location', { assign, pathname: '/' });
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
      await expect(apiFetch(path, { method: 'POST' })).rejects.toMatchObject({
        name: 'ApiError', status: 401,
      });
      expect(assign).not.toHaveBeenCalled();
    },
  );

  test('does not reload login when the session check returns 401', async () => {
    const assign = vi.fn();
    vi.stubGlobal('location', { assign, pathname: '/login' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    await expect(apiFetch('/api/auth/me')).rejects.toMatchObject({ name: 'ApiError', status: 401 });
    expect(assign).not.toHaveBeenCalled();
  });

  test('rejects other failed responses without redirecting', async () => {
    const assign = vi.fn();
    vi.stubGlobal('location', { assign, pathname: '/' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 500 })));
    await expect(apiFetch('/api/accounts')).rejects.toBeInstanceOf(ApiError);
    expect(assign).not.toHaveBeenCalled();
  });
});
