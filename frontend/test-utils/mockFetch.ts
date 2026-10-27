// A scripted `fetch` for tests: nothing here talks to a network. Each call is answered by the first
// matching route, and every request is recorded so a test can assert exactly what was sent.

export type RecordedRequest = {
  method: string;
  url: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
};

export type Reply = { status: number; body?: unknown } | 'network-error' | 'hang';
// A function may answer later (return a promise), to hold a request open while a test looks at the
// screen.
type Responder = Reply | ((request: RecordedRequest) => Reply | Promise<Reply>);

export type MockFetch = {
  requests: RecordedRequest[];
  // The next request to this method and path gets this reply (routes are used in the order added;
  // the last one for a path is kept for any further requests).
  on: (method: string, path: string, reply: Responder) => void;
  reset: () => void;
};

export function installMockFetch(): MockFetch {
  const routes: { method: string; path: string; replies: Responder[] }[] = [];
  const requests: RecordedRequest[] = [];

  const fetchMock = jest.fn(async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    const path = new URL(url).pathname;
    const method = init?.method ?? 'GET';
    const request: RecordedRequest = {
      method,
      url,
      path,
      headers: { ...((init?.headers as Record<string, string> | undefined) ?? {}) },
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    };
    requests.push(request);

    const route = routes.find((r) => r.method === method && r.path === path);
    if (!route) throw new Error(`Unexpected request: ${method} ${path}`);
    const responder = route.replies.length > 1 ? route.replies.shift()! : route.replies[0];
    const reply = await (typeof responder === 'function' ? responder(request) : responder);

    if (reply === 'network-error') throw new TypeError('Network request failed');
    if (reply === 'hang') {
      return new Promise((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new Error('aborted')));
      });
    }
    return {
      ok: reply.status >= 200 && reply.status < 300,
      status: reply.status,
      json: async () => {
        if (reply.body === undefined) throw new SyntaxError('no body');
        return reply.body;
      },
    };
  });
  (globalThis as { fetch: unknown }).fetch = fetchMock;

  return {
    requests,
    on(method, path, reply) {
      const existing = routes.find((r) => r.method === method && r.path === path);
      if (existing) existing.replies.push(reply);
      else routes.push({ method, path, replies: [reply] });
    },
    reset() {
      routes.length = 0;
      requests.length = 0;
      fetchMock.mockClear();
    },
  };
}

// A JWT shaped like the backend's (header.payload.signature, payload with `sub`). The signature is
// fake: the app never checks it, the backend does.
export function fakeToken(userId: number | string): string {
  const encode = (value: object) =>
    btoa(JSON.stringify(value)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode({ sub: String(userId), iat: 1, exp: 2 })}.signature`;
}
