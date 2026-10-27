import { apiRequest, ApiError, isRecord } from './client';
import type { Credentials, Session } from './types';

// POST /auth/login and POST /auth/register: both answer {"access_token": "<jwt>"} (the first 200,
// the second 201) and take nothing but the email and the password.
export function login(credentials: Credentials): Promise<Session> {
  return authenticate('/auth/login', credentials);
}

export function register(credentials: Credentials): Promise<Session> {
  return authenticate('/auth/register', credentials);
}

async function authenticate(path: string, credentials: Credentials): Promise<Session> {
  const data = await apiRequest(path, {
    method: 'POST',
    // the backend ignores surrounding spaces in an email; a password is sent exactly as typed
    body: { email: credentials.email.trim(), password: credentials.password },
  });
  if (!isRecord(data) || typeof data.access_token !== 'string' || data.access_token === '') {
    throw new ApiError('invalid-response', null, null);
  }
  return { token: data.access_token, userId: userIdFromToken(data.access_token) };
}

// The backend names the user in the token's `sub` claim (backend/app/core/security.py) and has no
// "who am I" route, so the app reads it to build /users/{id}/profile. It is only a path: the
// backend checks the token on every request and answers 404 for any id but its owner's.
export function userIdFromToken(token: string): number {
  try {
    const payload = token.split('.')[1];
    if (!payload) throw new Error('no payload');
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    const claims: unknown = JSON.parse(atob(base64 + '='.repeat((4 - (base64.length % 4)) % 4)));
    if (isRecord(claims) && typeof claims.sub === 'string' && /^[1-9]\d*$/.test(claims.sub)) {
      return Number(claims.sub);
    }
  } catch {
    // falls through to the error below
  }
  throw new ApiError('invalid-response', null, null);
}
