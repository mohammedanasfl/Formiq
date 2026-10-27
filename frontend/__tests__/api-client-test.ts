import {
  ApiError,
  createProfile,
  describeError,
  hasProfile,
  listEquipment,
  login,
  register,
  userIdFromToken,
  type ProfileCreate,
} from '../src/api';
import { apiRequest } from '../src/api/client';
import { API_BASE_URL } from '../src/api/config';
import { fakeToken, installMockFetch, type MockFetch } from '../test-utils/mockFetch';

let backend: MockFetch;

beforeEach(() => {
  backend = installMockFetch();
});

const PROFILE: ProfileCreate = {
  first_name: 'Sam',
  age: 30,
  height_cm: 175,
  weight_kg: 70,
  gender: 'other',
  fitness_experience: 'beginner',
  goal: 'build_muscle',
  training_frequency_per_week: 3,
  training_location: 'gym',
  activity_level: 'moderate',
  sleep_hours: 7.5,
  equipment_ids: [1, 3],
  no_equipment: false,
};

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    return error as ApiError;
  }
  throw new Error('expected the request to fail');
}

describe('sign in and sign up', () => {
  test.each([
    ['login', '/auth/login', login, 200],
    ['register', '/auth/register', register, 201],
  ] as const)('%s posts only the email and the password, and returns who signed in', async (_name, path, call, status) => {
    backend.on('POST', path, { status, body: { access_token: fakeToken(42), token_type: 'bearer' } });

    const session = await call({ email: '  sam@example.com ', password: ' pass word ' });

    expect(session).toEqual({ token: fakeToken(42), userId: 42 });
    const [request] = backend.requests;
    expect(request.url).toBe(`${API_BASE_URL}${path}`);
    expect(request.method).toBe('POST');
    // the email is trimmed; the password is exactly what was typed; nothing else is sent
    expect(request.body).toEqual({ email: 'sam@example.com', password: ' pass word ' });
    expect(request.headers).toMatchObject({
      'Content-Type': 'application/json',
      Accept: 'application/json',
    });
    expect(request.headers.Authorization).toBeUndefined();
  });

  test('a wrong password is an error, never a session', async () => {
    backend.on('POST', '/auth/login', { status: 401, body: { detail: 'invalid email or password' } });

    const error = await failure(login({ email: 'a@b.c', password: 'nope' }));

    expect(error).toMatchObject({ kind: 'http', status: 401, detail: 'invalid email or password' });
  });

  test('an email that already has an account is a 409', async () => {
    backend.on('POST', '/auth/register', {
      status: 409,
      body: { detail: 'an account with this email already exists' },
    });

    const error = await failure(register({ email: 'a@b.c', password: 'longenough' }));

    expect(error.status).toBe(409);
  });

  test.each([
    ['no token at all', {}],
    ['an empty token', { access_token: '' }],
    ['a token that is not a JWT', { access_token: 'abc' }],
    ['a token for no user', { access_token: fakeToken('abc') }],
  ])('an answer with %s is refused', async (_name, body) => {
    backend.on('POST', '/auth/login', { status: 200, body });

    const error = await failure(login({ email: 'a@b.c', password: 'x' }));

    expect(error.kind).toBe('invalid-response');
  });
});

describe('userIdFromToken', () => {
  test('reads the user id from the sub claim', () => {
    expect(userIdFromToken(fakeToken(7))).toBe(7);
    expect(userIdFromToken(fakeToken(2147483647))).toBe(2147483647);
  });

  test.each(['0', '07', '-1', '1.5', '1e3', ' 1', ''])('refuses the sub %j', (sub) => {
    expect(() => userIdFromToken(fakeToken(sub))).toThrow(ApiError);
  });

  test.each(['', 'nodots', 'a.b', 'a.!!!.c'])('refuses the malformed token %j', (token) => {
    expect(() => userIdFromToken(token)).toThrow(ApiError);
  });
});

describe('profile', () => {
  const session = { token: 'jwt-for-7', userId: 7 };

  test('creating one posts the profile to the user path with the token, and resolves on 201', async () => {
    backend.on('POST', '/users/7/profile', { status: 201, body: { id: 1, user_id: 7 } });

    await expect(createProfile(session, PROFILE)).resolves.toBeUndefined();

    const [request] = backend.requests;
    expect(request.method).toBe('POST');
    expect(request.path).toBe('/users/7/profile');
    expect(request.headers.Authorization).toBe('Bearer jwt-for-7');
    expect(request.body).toEqual(PROFILE);
  });

  test.each([
    [409, 'a profile already exists'],
    [401, 'not authenticated'],
    [422, undefined],
    [500, undefined],
  ])('a %i answer is a failure, not a saved profile', async (status, detail) => {
    backend.on('POST', '/users/7/profile', { status, body: detail ? { detail } : undefined });

    const error = await failure(createProfile(session, PROFILE));

    expect(error).toMatchObject({ kind: 'http', status });
  });

  test('has one when the backend answers 200, and has none on 404', async () => {
    backend.on('GET', '/users/7/profile', { status: 200, body: {} });
    backend.on('GET', '/users/7/profile', { status: 404, body: { detail: 'no profile found' } });

    await expect(hasProfile(session)).resolves.toBe(true);
    await expect(hasProfile(session)).resolves.toBe(false);
    expect(backend.requests[0].headers.Authorization).toBe('Bearer jwt-for-7');
  });

  test('any other answer to the check is an error, not "no profile"', async () => {
    backend.on('GET', '/users/7/profile', { status: 401 });

    expect((await failure(hasProfile(session))).status).toBe(401);
  });
});

describe('equipment', () => {
  test('lists the catalog equipment without signing in, leaving out entries it cannot read', async () => {
    backend.on('GET', '/equipment', {
      status: 200,
      body: [
        { id: 1, name: 'Dumbbell', description: null, is_active: true },
        { id: 2, name: '  ' },
        { id: 'x', name: 'Bad id' },
        'nonsense',
        { id: 3, name: 'Kettlebell' },
      ],
    });

    await expect(listEquipment()).resolves.toEqual([
      { id: 1, name: 'Dumbbell' },
      { id: 3, name: 'Kettlebell' },
    ]);
    expect(backend.requests[0].headers.Authorization).toBeUndefined();
  });

  test('something that is not a list is refused', async () => {
    backend.on('GET', '/equipment', { status: 200, body: { items: [] } });

    expect((await failure(listEquipment())).kind).toBe('invalid-response');
  });
});

describe('failures', () => {
  test('no connection is a network error', async () => {
    backend.on('GET', '/equipment', 'network-error');

    expect((await failure(listEquipment())).kind).toBe('network');
  });

  test('no answer in time is a timeout', async () => {
    backend.on('GET', '/slow', 'hang');

    expect((await failure(apiRequest('/slow', { timeoutMs: 20 }))).kind).toBe('timeout');
  });

  test('reads the detail of a plain and of a validation error, and ignores a body that is not JSON', async () => {
    backend.on('GET', '/a', { status: 400, body: { detail: 'a password has 8 to 1024 characters' } });
    backend.on('GET', '/b', { status: 422, body: { detail: [{ loc: ['body'], msg: 'field required' }] } });
    backend.on('GET', '/c', { status: 502 });

    expect((await failure(apiRequest('/a'))).detail).toBe('a password has 8 to 1024 characters');
    expect((await failure(apiRequest('/b'))).detail).toBe('field required');
    expect((await failure(apiRequest('/c'))).detail).toBeNull();
  });
});

describe('describeError', () => {
  const http = (status: number, detail: string | null = null) => new ApiError('http', status, detail);

  test.each([
    [new ApiError('network', null, null), 'signIn', "Can't reach Formiq. Check your connection and try again."],
    [new ApiError('timeout', null, null), 'saveProfile', 'Formiq took too long to answer. Try again.'],
    [http(401), 'signIn', 'Incorrect email or password.'],
    [http(401), 'saveProfile', 'Your session has expired. Log in again.'],
    [http(409), 'signUp', 'An account with this email already exists. Log in instead.'],
    [http(400, 'a password has 8 to 1024 characters'), 'signUp', 'A password has 8 to 1024 characters.'],
    [http(422), 'saveProfile', "Formiq couldn't accept some of your details. Go back and check them."],
    [http(503), 'signIn', "Formiq isn't available right now. Try again in a moment."],
    [http(500), 'saveProfile', "Something went wrong on Formiq's side. Try again."],
    [new Error('boom'), 'signIn', 'Something went wrong. Try again.'],
  ] as const)('%#: says what happened without claiming success', (error, context, message) => {
    expect(describeError(error, context)).toBe(message);
  });
});
