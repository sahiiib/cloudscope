export class ApiError extends Error {
  constructor(public readonly status: number) {
    super(`API request failed (${status})`);
    this.name = 'ApiError';
  }
}

/** Fetch a same-origin API endpoint; callers decode the response body. */
export async function apiFetch(
  path: `/api/${string}`,
  options: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(options.headers);
  headers.set('X-Requested-With', 'cloudscope');

  const response = await fetch(path, {
    ...options,
    headers,
    credentials: 'same-origin',
  });

  const isLoginRequest =
    path.startsWith('/api/auth/login') || path.startsWith('/api/auth/mfa/verify-login');
  if (response.status === 401 && !isLoginRequest && window.location.pathname !== '/login') {
    window.location.assign('/login');
  }
  if (!response.ok) {
    throw new ApiError(response.status);
  }
  return response;
}
