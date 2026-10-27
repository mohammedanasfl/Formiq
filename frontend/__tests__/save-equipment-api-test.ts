import { ApiError, describeError, saveEquipment } from '../src/api';
import { apiRequest } from '../src/api/client';
import { fakeToken, installMockFetch, type MockFetch } from '../test-utils/mockFetch';

let backend: MockFetch;

beforeEach(() => {
  backend = installMockFetch();
});

const SESSION = { token: fakeToken(7), userId: 7 };

// UserProfileResponse as the backend sends it after a PATCH: the equipment it kept
const profileBody = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  user_id: 7,
  first_name: 'Sam',
  no_equipment: false,
  equipment: [
    { id: 1, name: 'Dumbbell' },
    { id: 3, name: 'Kettlebell' },
  ],
  ...overrides,
});

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    return error as ApiError;
  }
  throw new Error('expected a failure');
}

describe('apiRequest PATCH', () => {
  test('sends a PATCH with the JSON body and the token', async () => {
    backend.on('PATCH', '/thing', { status: 200, body: { ok: true } });

    await expect(apiRequest('/thing', { method: 'PATCH', body: { a: 1 }, token: 'abc' })).resolves.toEqual({ ok: true });

    const [request] = backend.requests;
    expect(request.method).toBe('PATCH');
    expect(request.body).toEqual({ a: 1 });
    expect(request.headers).toMatchObject({ 'Content-Type': 'application/json', Authorization: 'Bearer abc' });
  });

  test('no answer in time is a timeout, as for any other method', async () => {
    backend.on('PATCH', '/slow', 'hang');

    expect((await failure(apiRequest('/slow', { method: 'PATCH', body: {}, timeoutMs: 20 }))).kind).toBe('timeout');
  });
});

describe('saveEquipment', () => {
  test('patches the profile of the signed-in user, with the token and only the two equipment fields', async () => {
    backend.on('PATCH', '/users/7/profile', { status: 200, body: profileBody() });

    await saveEquipment(SESSION, { equipment_ids: [1, 3], no_equipment: false });

    expect(backend.requests).toHaveLength(1);
    const [request] = backend.requests;
    expect(request.method).toBe('PATCH');
    expect(request.path).toBe('/users/7/profile');
    expect(request.headers.Authorization).toBe(`Bearer ${SESSION.token}`);
    expect(request.body).toEqual({ equipment_ids: [1, 3], no_equipment: false });
  });

  test('sends "no equipment" as that, with no ids', async () => {
    backend.on('PATCH', '/users/7/profile', { status: 200, body: profileBody({ no_equipment: true, equipment: [] }) });

    const saved = await saveEquipment(SESSION, { equipment_ids: [], no_equipment: true });

    expect(backend.requests[0].body).toEqual({ equipment_ids: [], no_equipment: true });
    expect(saved).toEqual({ equipment: [], noEquipment: true });
  });

  test('resolves with what the backend kept, not with what was asked for', async () => {
    // asked for three, the backend kept two: the answer is the one that counts
    backend.on('PATCH', '/users/7/profile', { status: 200, body: profileBody() });

    const saved = await saveEquipment(SESSION, { equipment_ids: [1, 2, 3], no_equipment: false });

    expect(saved).toEqual({
      equipment: [
        { id: 1, name: 'Dumbbell' },
        { id: 3, name: 'Kettlebell' },
      ],
      noEquipment: false,
    });
  });

  test('reads an emptied list as "never said"', async () => {
    backend.on('PATCH', '/users/7/profile', { status: 200, body: profileBody({ equipment: [] }) });

    await expect(saveEquipment(SESSION, { equipment_ids: [], no_equipment: false })).resolves.toEqual({
      equipment: [],
      noEquipment: false,
    });
  });

  test.each([
    ['a refused equipment id', { status: 400, body: { detail: 'equipment 99 is not in the catalog' } }, 400],
    ['an expired session', { status: 401, body: { detail: 'not authenticated' } }, 401],
    ['a user with no profile', { status: 404, body: { detail: 'user 7 has no profile' } }, 404],
    ['a body the backend could not validate', { status: 422, body: { detail: [{ msg: 'bad' }] } }, 422],
    ['a server error', { status: 500 }, 500],
  ] as const)('is an error for %s, never a saved answer', async (_name, reply, status) => {
    backend.on('PATCH', '/users/7/profile', reply);

    const error = await failure(saveEquipment(SESSION, { equipment_ids: [1], no_equipment: false }));

    expect(error).toMatchObject({ kind: 'http', status });
  });

  test('is an error when there is no connection', async () => {
    backend.on('PATCH', '/users/7/profile', 'network-error');

    expect((await failure(saveEquipment(SESSION, { equipment_ids: [1], no_equipment: false }))).kind).toBe('network');
  });

  test.each([
    ['an answer that is not JSON', { status: 200 }],
    ['an answer with no equipment in it', { status: 200, body: { first_name: 'Sam' } }],
    ['an answer with a half-formed piece', { status: 200, body: profileBody({ equipment: [{ id: 1, name: 'Dumbbell' }, { id: 'x' }] }) }],
    ['an answer that says none and lists some', { status: 200, body: profileBody({ no_equipment: true }) }],
  ])('is an error for %s: nothing is claimed saved that the app cannot read', async (_name, reply) => {
    backend.on('PATCH', '/users/7/profile', reply);

    expect((await failure(saveEquipment(SESSION, { equipment_ids: [1], no_equipment: false }))).kind).toBe('invalid-response');
  });
});

describe('describeError for saving equipment', () => {
  const http = (status: number, detail: string | null = null) => new ApiError('http', status, detail);

  test.each([
    [http(401), 'Your session has expired. Log in again.'],
    [http(400, 'equipment 5 is retired (is_active is false)'), "Formiq couldn't accept some of that equipment. Go back, open the list again and choose again."],
    [http(404, 'user 7 has no profile'), 'Formiq could not find your profile, so nothing was changed.'],
    [http(422), "Formiq couldn't accept that equipment. Go back and choose again."],
    [http(500), "Something went wrong on Formiq's side. Try again."],
    [http(503), "Formiq isn't available right now. Try again in a moment."],
    [new ApiError('network', null, null), "Can't reach Formiq. Check your connection and try again."],
    [new ApiError('timeout', null, null), 'Formiq took too long to answer. Try again.'],
    [new ApiError('invalid-response', 200, null), 'Formiq sent an answer the app could not read. Try again.'],
    [new Error('boom'), 'Something went wrong. Try again.'],
  ])('%#: says a sentence that claims nothing was saved', (error, message) => {
    expect(describeError(error, 'saveEquipment')).toBe(message);
  });

  test('a 404 still reads as before for the other requests', () => {
    expect(describeError(http(404), 'savedEquipment')).toBe('Something went wrong. Try again.');
    expect(describeError(http(400, 'bad value'), 'saveProfile')).toBe('Bad value.');
  });
});
