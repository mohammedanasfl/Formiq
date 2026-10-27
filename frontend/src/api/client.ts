import { API_BASE_URL } from './config';

export type ApiErrorKind = 'network' | 'timeout' | 'http' | 'invalid-response';

// What went wrong, without the user-facing wording (see messages.ts). `status` is the HTTP status
// of an answer the backend gave, `detail` the message it sent with it.
export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    readonly status: number | null,
    readonly detail: string | null,
  ) {
    super(detail ?? kind);
    this.name = 'ApiError';
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH';
  body?: unknown;
  token?: string;
  timeoutMs?: number;
};

const DEFAULT_TIMEOUT_MS = 15_000;

// Sends one JSON request and returns the parsed JSON answer (undefined for an empty one).
// Anything but a 2xx answer throws an ApiError, so a caller can only carry on after the backend
// said yes.
export async function apiRequest(path: string, options: RequestOptions = {}): Promise<unknown> {
  const { method = 'GET', body, token, timeoutMs = DEFAULT_TIMEOUT_MS } = options;
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch {
      throw new ApiError(controller.signal.aborted ? 'timeout' : 'network', null, null);
    }

    if (!response.ok) {
      throw new ApiError('http', response.status, await readDetail(response));
    }
    if (response.status === 204) return undefined;
    try {
      return await response.json();
    } catch {
      throw new ApiError(controller.signal.aborted ? 'timeout' : 'invalid-response', response.status, null);
    }
  } finally {
    clearTimeout(timer);
  }
}

// FastAPI answers {"detail": "text"}, or {"detail": [{"msg": "text", ...}]} for a request it
// could not validate.
async function readDetail(response: Response): Promise<string | null> {
  try {
    const data: unknown = await response.json();
    if (!isRecord(data)) return null;
    const { detail } = data;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && isRecord(detail[0]) && typeof detail[0].msg === 'string') {
      return detail[0].msg;
    }
  } catch {
    // not JSON: there is no detail
  }
  return null;
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
