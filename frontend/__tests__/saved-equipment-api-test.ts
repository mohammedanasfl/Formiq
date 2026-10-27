import { ApiError, getSavedEquipment, readSavedEquipment } from '../src/api';
import { fakeToken, installMockFetch, type MockFetch } from '../test-utils/mockFetch';

let backend: MockFetch;

beforeEach(() => {
  backend = installMockFetch();
});

const SESSION = { token: fakeToken(7), userId: 7 };

// UserProfileResponse as the backend sends it: the equipment is a list of pieces (id and name) and a flag
const profileBody = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  user_id: 7,
  first_name: 'Sam',
  last_name: null,
  age: 30,
  goal: 'build_muscle',
  no_equipment: false,
  equipment: [
    { id: 1, name: 'Dumbbell' },
    { id: 3, name: 'Kettlebell' },
  ],
  created_at: '2026-10-27T09:00:00Z',
  updated_at: '2026-10-27T09:00:00Z',
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

describe('readSavedEquipment', () => {
  test('reads the pieces the person has, with their catalog ids', () => {
    expect(readSavedEquipment(profileBody())).toEqual({
      equipment: [
        { id: 1, name: 'Dumbbell' },
        { id: 3, name: 'Kettlebell' },
      ],
      noEquipment: false,
    });
  });

  test('reads "no equipment" as that, with nothing listed', () => {
    expect(readSavedEquipment(profileBody({ no_equipment: true, equipment: [] }))).toEqual({
      equipment: [],
      noEquipment: true,
    });
  });

  test('reads a profile that never said as neither', () => {
    expect(readSavedEquipment(profileBody({ equipment: [] }))).toEqual({ equipment: [], noEquipment: false });
  });

  test('keeps the order the backend gave', () => {
    const read = readSavedEquipment(
      profileBody({
        equipment: [
          { id: 9, name: 'Bench' },
          { id: 2, name: 'Barbell' },
        ],
      }),
    );

    expect(read.equipment.map((item) => item.name)).toEqual(['Bench', 'Barbell']);
  });

  test.each([
    ['an answer that is not an object', 'profile'],
    ['an array', []],
    ['no flag', { equipment: [] }],
    ['a flag that is not a boolean', { no_equipment: 'no', equipment: [] }],
    ['no list', { no_equipment: false }],
    ['a list that is not a list', { no_equipment: false, equipment: 'Dumbbell' }],
    ['a piece with no id', { no_equipment: false, equipment: [{ name: 'Bench' }] }],
    ['a piece with an id that is not a whole number', { no_equipment: false, equipment: [{ id: 1.5, name: 'Bench' }] }],
    ['a piece with an id as text', { no_equipment: false, equipment: [{ id: '1', name: 'Bench' }] }],
    ['a piece with no name', { no_equipment: false, equipment: [{ id: 1 }] }],
    ['a piece with a blank name', { no_equipment: false, equipment: [{ id: 1, name: '  ' }] }],
    ['a piece that is not an object', { no_equipment: false, equipment: ['Bench'] }],
    ['no equipment and a list of equipment too', { no_equipment: true, equipment: [{ id: 1, name: 'Bench' }] }],
  ])('refuses %s, whole', (_name, data) => {
    // never trimmed: half a list shown as the person's equipment would be a wrong answer
    expect(() => readSavedEquipment(data)).toThrow(ApiError);
    try {
      readSavedEquipment(data);
    } catch (error) {
      expect((error as ApiError).kind).toBe('invalid-response');
    }
  });
});

describe('getSavedEquipment', () => {
  test('reads the profile of the signed-in user with their token', async () => {
    backend.on('GET', '/users/7/profile', { status: 200, body: profileBody() });

    const saved = await getSavedEquipment(SESSION);

    expect(saved?.equipment.map((item) => item.name)).toEqual(['Dumbbell', 'Kettlebell']);
    expect(backend.requests).toHaveLength(1);
    expect(backend.requests[0].method).toBe('GET');
    expect(backend.requests[0].headers.Authorization).toBe(`Bearer ${SESSION.token}`);
  });

  test('says there is nothing to read when the user has no profile yet', async () => {
    backend.on('GET', '/users/7/profile', { status: 404, body: { detail: 'no profile found for user 7' } });

    await expect(getSavedEquipment(SESSION)).resolves.toBeNull();
  });

  test.each([
    ['a server error', { status: 500 }],
    ['an expired session', { status: 401 }],
    ['an answer that is not JSON', { status: 200 }],
    ['an answer the app cannot read', { status: 200, body: { no_equipment: 1 } }],
    ['no connection', 'network-error' as const],
  ])('is an error for %s, never an answer', async (_name, reply) => {
    backend.on('GET', '/users/7/profile', reply);

    await failure(getSavedEquipment(SESSION));
  });
});
