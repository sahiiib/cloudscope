import { ApiError } from '../api/client';

export function settingsError(error: unknown, fallback: string, conflict = 'This setting changed. Refresh and try again.') {
  if (!(error instanceof ApiError)) return fallback;
  switch (error.status) {
    case 401: return 'Credentials or code were not accepted, or your session expired. Try a fresh code or sign in again.';
    case 403: return 'You do not have permission to perform this action.';
    case 409: return conflict;
    case 422: return 'Check the fields and try again. Passwords need at least 12 characters and codes need six digits.';
    case 429: return 'Too many attempts. Please wait before trying again.';
    default: return fallback;
  }
}
