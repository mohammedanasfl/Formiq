import {
  ApiError,
  approveProposal,
  COACH_TIMEOUT_MS,
  deviceTimeZone,
  getPendingProposals,
  readCoachReply,
  readPendingProposals,
  rejectProposal,
  sendCoachMessage,
} from '../src/api';
import { API_BASE_URL } from '../src/api/config';
import { createApiCoachGateway } from '../src/coach/apiGateway';
import { fakeToken, installMockFetch, type MockFetch } from '../test-utils/mockFetch';
import golden from './fixtures/coach-message-responses.json';
import pendings from './fixtures/pending-proposals-responses.json';
import savedPlan from './fixtures/saved-plan-response.json';

// The fixtures are what the backend's own response models produce (backend/app/schemas/coach.py and workout_plan.py,
// as Phase 2.1 changed them), written out by a script that builds a CoachMessageResponse, a PendingProposalsResponse
// and a WorkoutPlanResponse and dumps them as the routes would: a contract check against the real schema, not a copy
// of the app's own types.

const SESSION = { token: fakeToken(7), userId: 7 };
const PROPOSAL_ID = 'a'.repeat(32);
const BINDING = 'b'.repeat(64);

let backend: MockFetch;

beforeEach(() => {
  backend = installMockFetch();
});

afterEach(() => {
  jest.useRealTimers();
});

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    return error as ApiError;
  }
  throw new Error('expected the request to fail');
}

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value));

describe('POST /coach/message', () => {
  test('sends the message and the earlier turns with the token, and nothing else: no user, no plan to change', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_only });

    await sendCoachMessage(SESSION, {
      message: 'Create a 25-minute upper-body workout.',
      history: [
        { role: 'coach', text: 'Hi' },
        { role: 'user', text: 'Hello' },
      ],
    });

    const [request] = backend.requests;
    expect(request.url).toBe(`${API_BASE_URL}/coach/message`);
    expect(request.method).toBe('POST');
    expect(request.headers.Authorization).toBe(`Bearer ${SESSION.token}`);
    expect(request.body).toEqual({
      message: 'Create a 25-minute upper-body workout.',
      history: [
        { role: 'coach', text: 'Hi' },
        { role: 'user', text: 'Hello' },
      ],
    });
  });

  test('sends the workout the conversation is about as workout_plan_id, and only when there is one', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_only });

    await sendCoachMessage(SESSION, { message: 'shorter', history: [], workoutPlanId: 41 });
    await sendCoachMessage(SESSION, { message: 'shorter', history: [], workoutPlanId: undefined });

    expect(backend.requests[0].body).toEqual({ message: 'shorter', history: [], workout_plan_id: 41 });
    // left out, never null or 0: a request about no workout is as it was before the field existed
    expect(backend.requests[1].body).toEqual({ message: 'shorter', history: [] });
    expect(backend.requests[1].body).not.toHaveProperty('workout_plan_id');
  });

  test.each([0, -3, 1.5, Number.NaN, 2_147_483_648])('is not sent with workout plan id %s', async (workoutPlanId) => {
    const error = await failure(sendCoachMessage(SESSION, { message: 'hi', history: [], workoutPlanId }));

    expect(error.status).toBe(422);
    expect(backend.requests).toHaveLength(0);
  });

  test("reads a reply that proposes nothing (the backend leaves `proposal` out): the coach's words and no workout", async () => {
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_only });

    expect(await sendCoachMessage(SESSION, { message: 'hi', history: [] })).toEqual({
      reply: 'Which workout do you mean?',
      proposal: null,
    });
  });

  test("reads a proposal that revises a saved workout, as the backend's own response model writes it", async () => {
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_with_revision });

    const { reply, proposal } = await sendCoachMessage(SESSION, { message: 'a different ab workout', history: [] });

    expect(reply).toBe('Here is an updated version.');
    expect(proposal).toMatchObject({
      proposal_id: PROPOSAL_ID,
      binding: BINDING,
      name: 'Core Stability & Abs',
      scheduled_date: '2026-10-22',
      warm_up_minutes: 1,
      main_minutes: 14,
      cool_down_minutes: 1,
      estimated_minutes: 16,
      revision: {
        replaces_plan_id: 41,
        replaces_plan_name: 'Core & Abs Focus',
        kind: 'ADJUST',
        kept_exercises: ['Plank', 'Goblet Squat'],
        // how long the plan it replaces takes: the backend's, so the card never has to guess
        replaces_plan_estimated_minutes: 17,
      },
      coverage: { complete: true, focus: 'CORE', trained_regions: ['CORE'], missing_regions: [], limitations: [] },
    });
    expect(proposal?.exercises.map((exercise) => [exercise.section, exercise.exercise_name, exercise.reps, exercise.duration_seconds])).toEqual([
      ['WARM_UP', 'Cat-Cow Stretch', null, 40],
      ['MAIN_WORKOUT', 'Plank', null, 30],
      ['MAIN_WORKOUT', 'Dead Bug', 10, null],
      ['MAIN_WORKOUT', 'Goblet Squat', 10, null],
      ['COOL_DOWN', "Child's Pose", null, 45],
    ]);
    expect(proposal?.exercises[2]).toMatchObject({ equipment: ['Exercise Mat'], notes: 'Slow and controlled', rest_seconds: 45 });
  });

  test("reads the backend's own comparison with the plan it replaces, with each prescription's numbers and its wording", async () => {
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_with_revision });

    const { proposal } = await sendCoachMessage(SESSION, { message: 'a different ab workout', history: [] });

    const changes = proposal?.changes;
    expect(changes).toMatchObject({
      compared_with_plan_id: 41,
      compared_with_plan_name: 'Core & Abs Focus',
      compared_with_scheduled_date: '2026-10-22',
      unchanged: ['Plank', "Child's Pose"],
      name_changed: true,
      scheduled_date_changed: false,
      identical: false,
    });
    expect(changes?.added).toEqual([
      {
        section: 'MAIN_WORKOUT',
        exercise_name: 'Dead Bug',
        before: null,
        after: { sets: 3, reps: 10, duration_seconds: null, rest_seconds: 45, weight_kg: null, summary: '3 sets of 10 reps, 45 s rest' },
      },
    ]);
    expect(changes?.removed.map((item) => [item.exercise_name, item.before?.summary, item.after])).toEqual([
      ['Bicycle Crunch', '3 sets of 20 reps, 45 s rest', null],
    ]);
    // a weight the saved plan has and the proposal does not is a change the backend lists
    expect(changes?.changed.map((item) => [item.exercise_name, item.before?.weight_kg, item.after?.weight_kg])).toEqual([
      ['Cat-Cow Stretch', null, null],
      ['Goblet Squat', 20, null],
    ]);
  });

  test('reads a proposal the backend could not compare: no length and no changes, both null', () => {
    const { proposal } = readCoachReply(golden.reply_with_revision_not_compared);

    expect(proposal?.revision?.replaces_plan_estimated_minutes).toBeNull();
    expect(proposal?.changes).toBeNull();
  });

  test('reads a proposal for a new workout: its revision is null', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_with_new_workout });

    const { proposal } = await sendCoachMessage(SESSION, { message: 'a new workout', history: [] });

    expect(proposal?.proposal_id).toBe('c'.repeat(32));
    expect(proposal?.revision).toBeNull();
    // nothing to compare a new workout with
    expect(proposal?.changes).toBeNull();
  });

  test('what the backend leaves out or sends as null reads as null: a revision, its changes, reps, duration, rest and notes', () => {
    const body = clone(golden.reply_with_revision) as any;
    delete body.proposal.revision;
    delete body.proposal.changes;
    for (const exercise of body.proposal.exercises) {
      delete exercise.reps;
      delete exercise.duration_seconds;
      delete exercise.rest_seconds;
      delete exercise.notes;
    }

    const { proposal } = readCoachReply(body);

    expect(proposal?.revision).toBeNull();
    expect(proposal?.changes).toBeNull();
    for (const exercise of proposal!.exercises) {
      expect([exercise.reps, exercise.duration_seconds, exercise.rest_seconds, exercise.notes]).toEqual([null, null, null, null]);
    }
  });

  test('a replaced plan length and a prescription that are left out read as null', () => {
    const body = clone(golden.reply_with_revision) as any;
    delete body.proposal.revision.replaces_plan_estimated_minutes;
    delete body.proposal.changes.compared_with_scheduled_date;
    for (const item of body.proposal.changes.changed) {
      delete item.before.reps;
      delete item.before.weight_kg;
    }

    const { proposal } = readCoachReply(body);

    expect(proposal?.revision?.replaces_plan_estimated_minutes).toBeNull();
    expect(proposal?.changes?.compared_with_scheduled_date).toBeNull();
    expect(proposal?.changes?.changed[0].before).toMatchObject({ reps: null, weight_kg: null });
  });

  test('an explicit null proposal is no proposal', () => {
    expect(readCoachReply({ reply: 'Hello', proposal: null })).toEqual({ reply: 'Hello', proposal: null });
  });

  test('a limitation with no region reads as null (the main workout is short of exercises)', () => {
    const body = clone(golden.reply_with_new_workout) as any;
    body.proposal.coverage = {
      ...body.proposal.coverage,
      complete: false,
      limitations: [{ code: 'TOO_FEW_SUITABLE_EXERCISES', message: 'Only two suitable exercises.' }],
    };

    expect(readCoachReply(body).proposal?.coverage.limitations).toEqual([
      { code: 'TOO_FEW_SUITABLE_EXERCISES', region: null, message: 'Only two suitable exercises.' },
    ]);
  });

  describe('the weight of an exercise (weight_kg, kilograms)', () => {
    test("is read as the backend sends it: null for no weight, a number for one, fractions included", () => {
      const body = clone(golden.reply_with_revision) as any;
      body.proposal.exercises[1].weight_kg = 20;
      body.proposal.exercises[2].weight_kg = 12.5;

      const { proposal } = readCoachReply(body);

      expect(proposal?.exercises.map((exercise) => exercise.weight_kg)).toEqual([null, 20, 12.5, ...proposal!.exercises.slice(3).map(() => null)]);
    });

    test('is on every exercise of every fixture the backend wrote, and reads as null there', () => {
      for (const reply of [golden.reply_with_revision, golden.reply_with_new_workout, golden.reply_with_revision_not_compared]) {
        for (const exercise of (reply as any).proposal.exercises) expect(exercise).toHaveProperty('weight_kg', null);
        const { proposal } = readCoachReply(clone(reply));
        expect(proposal!.exercises.length).toBeGreaterThan(0);
        for (const exercise of proposal!.exercises) expect(exercise.weight_kg).toBeNull();
      }
    });

    test('an answer from before the field existed (no weight_kg) reads as no weight, not as an error', () => {
      const body = clone(golden.reply_with_new_workout) as any;
      for (const exercise of body.proposal.exercises) delete exercise.weight_kg;

      const { proposal } = readCoachReply(body);

      expect(proposal!.exercises.length).toBeGreaterThan(0);
      for (const exercise of proposal!.exercises) expect(exercise).toHaveProperty('weight_kg', null);
    });

    test('is read in the waiting list too, and a list from before the field reads as no weight', () => {
      const body = clone(pendings.one) as any;
      body.proposals[0].exercises[1].weight_kg = 15;
      const older = clone(pendings.two) as any;
      for (const proposal of older.proposals) for (const exercise of proposal.exercises) delete exercise.weight_kg;

      expect(readPendingProposals(body)[0].exercises.map((exercise) => exercise.weight_kg).slice(0, 3)).toEqual([null, 15, null]);
      for (const proposal of readPendingProposals(older)) for (const exercise of proposal.exercises) expect(exercise.weight_kg).toBeNull();
    });

    test.each<[string, unknown]>([
      ['text', '20 kg'],
      ['a number as text', '20'],
      ['true', true],
      ['an object', { kg: 20 }],
      ['a list', [20]],
    ])('is refused with the whole answer when it is %s', (_name, weight) => {
      const body = clone(golden.reply_with_revision) as any;
      body.proposal.exercises[1].weight_kg = weight;
      const pending = clone(pendings.one) as any;
      pending.proposals[0].exercises[1].weight_kg = weight;

      expect(() => readCoachReply(body)).toThrow(ApiError);
      expect(() => readPendingProposals(pending)).toThrow(ApiError);
    });
  });

  test('the extra fields a newer backend may send are left behind', () => {
    const body = clone(golden.reply_with_new_workout) as any;
    body.proposal.difficulty = 'Moderate';
    body.proposal.exercises[0].video_url = 'x';
    body.something_new = true;

    const { proposal } = readCoachReply(body);

    expect(proposal).not.toHaveProperty('difficulty');
    expect(proposal?.exercises[0]).not.toHaveProperty('video_url');
  });

  // An answer that cannot be read in full is refused as a whole: a workout shown with a piece missing could be
  // applied without the person ever seeing it.
  test.each<[string, (body: any) => void]>([
    ['no reply', (body) => delete body.reply],
    ['a reply that is not text', (body) => (body.reply = 5)],
    ['a proposal that is not an object', (body) => (body.proposal = 'workout')],
    ['a proposal id that is not 32 hex digits', (body) => (body.proposal.proposal_id = 'abc')],
    ['a binding that is not 64 hex digits', (body) => (body.proposal.binding = 'f'.repeat(63))],
    ['an expiry that is not a time', (body) => (body.proposal.expires_at = 'soon')],
    ['an empty title', (body) => (body.proposal.name = '  ')],
    ['a day that is not a date', (body) => (body.proposal.scheduled_date = '22/10/2026')],
    ['exercises that are not a list', (body) => (body.proposal.exercises = null)],
    ['an exercise in a section the app does not know', (body) => (body.proposal.exercises[1].section = 'STRETCH')],
    ['an exercise with no name', (body) => delete body.proposal.exercises[1].exercise_name],
    ['reps that are text', (body) => (body.proposal.exercises[2].reps = '10')],
    ['sets that are not whole', (body) => (body.proposal.exercises[2].sets = 2.5)],
    ['equipment that is not a list of names', (body) => (body.proposal.exercises[2].equipment = [3])],
    ['minutes that are not whole numbers', (body) => (body.proposal.estimated_minutes = '16')],
    ['no coverage', (body) => delete body.proposal.coverage],
    ['a focus the app does not know', (body) => (body.proposal.coverage.focus = 'CARDIO')],
    ['a limitation of an unknown kind', (body) => (body.proposal.coverage.limitations = [{ code: 'OTHER', region: null, message: 'x' }])],
    ['a revision of an unknown kind', (body) => (body.proposal.revision.kind = 'REPLACE')],
    ['a revision with no plan id', (body) => delete body.proposal.revision.replaces_plan_id],
    ['a revision that keeps something that is not a name', (body) => (body.proposal.revision.kept_exercises = [1])],
    ['a replaced plan length that is text', (body) => (body.proposal.revision.replaces_plan_estimated_minutes = '17')],
    ['a replaced plan length that is not whole', (body) => (body.proposal.revision.replaces_plan_estimated_minutes = 17.5)],
    ['changes that are not an object', (body) => (body.proposal.changes = 'none')],
    ['changes with no plan id', (body) => delete body.proposal.changes.compared_with_plan_id],
    ['changes of another plan than the one the proposal replaces', (body) => (body.proposal.changes.compared_with_plan_id = 42)],
    ['changes on a proposal that replaces nothing', (body) => (body.proposal.revision = null)],
    ['changes with a plan day that is not a date', (body) => (body.proposal.changes.compared_with_scheduled_date = 'Thu')],
    ['changes with no list of exercises added', (body) => delete body.proposal.changes.added],
    ['changes whose unchanged are not names', (body) => (body.proposal.changes.unchanged = [3])],
    ['changes whose flag is not true or false', (body) => (body.proposal.changes.identical = 'no')],
    ['an added exercise that has a before', (body) => (body.proposal.changes.added[0].before = body.proposal.changes.added[0].after)],
    ['an added exercise with no after', (body) => (body.proposal.changes.added[0].after = null)],
    ['a removed exercise that has an after', (body) => (body.proposal.changes.removed[0].after = body.proposal.changes.removed[0].before)],
    ['a changed exercise with no before', (body) => (body.proposal.changes.changed[0].before = null)],
    ['a changed exercise with no after', (body) => (body.proposal.changes.changed[0].after = null)],
    ['a changed exercise in a section the app does not know', (body) => (body.proposal.changes.changed[0].section = 'STRETCH')],
    ['a changed exercise with no name', (body) => (body.proposal.changes.changed[0].exercise_name = ' ')],
    ['a prescription with no sets', (body) => delete body.proposal.changes.added[0].after.sets],
    ['a prescription with reps that are text', (body) => (body.proposal.changes.added[0].after.reps = '10')],
    ['a prescription with a weight that is text', (body) => (body.proposal.changes.changed[1].before.weight_kg = '20 kg')],
    ['a prescription with no wording', (body) => delete body.proposal.changes.changed[0].after.summary],
  ])('refuses the whole answer for %s', async (_name, break_) => {
    const body = clone(golden.reply_with_revision) as any;
    break_(body);
    backend.on('POST', '/coach/message', { status: 200, body });

    const error = await failure(sendCoachMessage(SESSION, { message: 'hi', history: [] }));

    expect(error.kind).toBe('invalid-response');
  });

  test('an answer that is not JSON is refused', async () => {
    backend.on('POST', '/coach/message', { status: 200 });

    expect((await failure(sendCoachMessage(SESSION, { message: 'hi', history: [] }))).kind).toBe('invalid-response');
  });

  test.each([
    [401, 'could not validate credentials'],
    [404, 'user 7 does not exist'],
    [422, 'message: String should have at most 4000 characters'],
    [502, 'the AI coach could not answer; try again later'],
    [503, 'the AI coach is not configured'],
  ])('a %s answer is an ApiError with its status and detail', async (status, detail) => {
    backend.on('POST', '/coach/message', { status, body: { detail } });

    const error = await failure(sendCoachMessage(SESSION, { message: 'hi', history: [] }));

    expect([error.kind, error.status, error.detail]).toEqual(['http', status, detail]);
  });

  test('no connection is a network error', async () => {
    backend.on('POST', '/coach/message', 'network-error');

    expect((await failure(sendCoachMessage(SESSION, { message: 'hi', history: [] }))).kind).toBe('network');
  });

  test('waits far longer than a plain read for the coach, and then gives up', async () => {
    jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] });
    backend.on('POST', '/coach/message', 'hang');
    let outcome: unknown = 'pending';
    sendCoachMessage(SESSION, { message: 'hi', history: [] }).then(
      (value) => (outcome = value),
      (error) => (outcome = error),
    );

    // a plain read gives up after 15 s: the coach is still being waited for
    await jest.advanceTimersByTimeAsync(15_001);
    expect(outcome).toBe('pending');
    await jest.advanceTimersByTimeAsync(COACH_TIMEOUT_MS);

    expect(outcome).toBeInstanceOf(ApiError);
    expect((outcome as ApiError).kind).toBe('timeout');
  });
});

describe('POST /coach/message: the device time zone (Phase 2.7)', () => {
  const ZONE_REFUSED = {
    status: 422,
    body: { detail: [{ msg: 'Value error, timezone must be an IANA time zone name such as Asia/Kolkata or UTC' }] },
  };

  test('sends the device zone as `timezone`, and only when the caller has one', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_only });

    await sendCoachMessage(SESSION, { message: 'tomorrow', history: [], timeZone: 'Asia/Kolkata' });
    await sendCoachMessage(SESSION, { message: 'tomorrow', history: [], timeZone: undefined });

    expect(backend.requests[0].body).toEqual({ message: 'tomorrow', history: [], timezone: 'Asia/Kolkata' });
    // left out, never null or empty: a request without it is as it was before the field existed
    expect(backend.requests[1].body).toEqual({ message: 'tomorrow', history: [] });
    expect(backend.requests[1].body).not.toHaveProperty('timezone');
  });

  test('sends it together with the workout the conversation is about', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_only });

    await sendCoachMessage(SESSION, { message: 'tomorrow', history: [], workoutPlanId: 41, timeZone: 'UTC' });

    expect(backend.requests[0].body).toEqual({
      message: 'tomorrow',
      history: [],
      workout_plan_id: 41,
      timezone: 'UTC',
    });
  });

  test('asks once more without the zone when the backend does not know it, so the coach is never unreachable for it', async () => {
    backend.on('POST', '/coach/message', ZONE_REFUSED);
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_only });

    const reply = await sendCoachMessage(SESSION, { message: 'tomorrow', history: [], timeZone: 'Europe/Kyiv' });

    expect(reply.reply).toBe('Which workout do you mean?');
    expect(backend.requests).toHaveLength(2);
    expect(backend.requests[0].body).toHaveProperty('timezone', 'Europe/Kyiv');
    // the same message, the same history, nothing else changed
    expect(backend.requests[1].body).toEqual({ message: 'tomorrow', history: [] });
  });

  test('gives up after that one retry: a second refusal is the error', async () => {
    backend.on('POST', '/coach/message', ZONE_REFUSED);
    backend.on('POST', '/coach/message', { status: 500 });

    const error = await failure(sendCoachMessage(SESSION, { message: 'tomorrow', history: [], timeZone: 'Europe/Kyiv' }));

    expect(error.status).toBe(500);
    expect(backend.requests).toHaveLength(2);
  });

  test.each([
    ['another 422', { status: 422, body: { detail: [{ msg: 'String should have at most 4000 characters' }] } }],
    ['a plan that is not found', { status: 404, body: { detail: 'user 7 has no workout plan 41' } }],
    ['a workout that cannot be changed', { status: 409, body: { detail: 'workout plan 41 is CANCELLED' } }],
    ['an expired session', { status: 401, body: { detail: 'Not authenticated' } }],
    ['the coach being unavailable', { status: 502, body: { detail: 'the AI coach could not answer; try again later' } }],
    ['no network', 'network-error' as const],
  ])('is not retried for %s', async (_name, reply) => {
    backend.on('POST', '/coach/message', reply);

    const error = await failure(sendCoachMessage(SESSION, { message: 'tomorrow', history: [], timeZone: 'Asia/Kolkata' }));

    expect(error).toBeInstanceOf(ApiError);
    expect(backend.requests).toHaveLength(1);
  });

  test('is not retried when no zone was sent: there is nothing to leave out', async () => {
    backend.on('POST', '/coach/message', ZONE_REFUSED);

    const error = await failure(sendCoachMessage(SESSION, { message: 'tomorrow', history: [] }));

    expect(error.status).toBe(422);
    expect(backend.requests).toHaveLength(1);
  });

  test('is not retried for a reply that cannot be read: an answer was given', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: { nothing: 'useful' } });

    const error = await failure(sendCoachMessage(SESSION, { message: 'tomorrow', history: [], timeZone: 'UTC' }));

    expect(error.kind).toBe('invalid-response');
    expect(backend.requests).toHaveLength(1);
  });
});

describe('deviceTimeZone', () => {
  const resolvedAs = (value: unknown) =>
    jest.spyOn(Intl, 'DateTimeFormat').mockImplementation(
      () => ({ resolvedOptions: () => ({ timeZone: value }) }) as unknown as Intl.DateTimeFormat,
    );

  afterEach(() => jest.restoreAllMocks());

  test.each(['Asia/Kolkata', 'Asia/Calcutta', 'UTC', 'America/Argentina/Buenos_Aires', 'Etc/GMT+12', 'America/Port-au-Prince'])(
    'is the name the device reports, %s',
    (zone) => {
      resolvedAs(zone);

      expect(deviceTimeZone()).toBe(zone);
    },
  );

  test.each([undefined, null, '', 42, 'Not A Zone', '../etc/passwd', 'Asia/Kolkata; drop', 'A'.repeat(65), 'Asia/Kolkata\n'])(
    'is left out when the device reports %p: a name that is not shaped like one is never sent',
    (zone) => {
      resolvedAs(zone);

      expect(deviceTimeZone()).toBeUndefined();
    },
  );

  test('is left out when the platform has no Intl time zone at all', () => {
    jest.spyOn(Intl, 'DateTimeFormat').mockImplementation(() => {
      throw new Error('no Intl');
    });

    expect(deviceTimeZone()).toBeUndefined();
  });

  test('is the zone the real runtime reports, a name of the right shape', () => {
    const zone = deviceTimeZone();

    expect(zone === undefined || /^[A-Za-z0-9_+\-/]{1,64}$/.test(zone)).toBe(true);
  });
});

describe('POST /coach/proposals/{id}/approve', () => {
  const PATH = `/coach/proposals/${PROPOSAL_ID}/approve`;

  test('sends only the binding, with the token, and returns the plan the backend saved', async () => {
    backend.on('POST', PATH, { status: 201, body: savedPlan });

    const plan = await approveProposal(SESSION, { proposalId: PROPOSAL_ID, binding: BINDING });

    const [request] = backend.requests;
    expect(request.url).toBe(`${API_BASE_URL}${PATH}`);
    expect(request.headers.Authorization).toBe(`Bearer ${SESSION.token}`);
    expect(request.body).toEqual({ binding: BINDING });
    expect(plan).toMatchObject({ id: 77, name: 'Core Stability & Abs', status: 'PLANNED', scheduled_date: '2026-10-22' });
    expect(plan.exercises).toHaveLength(4);
  });

  test('a 200 is the same success: asking again after a lost answer returns the plan the first approval saved', async () => {
    backend.on('POST', PATH, { status: 200, body: savedPlan });

    const plan = await approveProposal(SESSION, { proposalId: PROPOSAL_ID, binding: BINDING });

    expect(plan).toMatchObject({ id: 77, name: 'Core Stability & Abs', status: 'PLANNED' });
  });

  test('a 200 whose plan cannot be read is no more a saved plan than a 201 is', async () => {
    backend.on('POST', PATH, { status: 200, body: { id: 77 } });

    expect((await failure(approveProposal(SESSION, { proposalId: PROPOSAL_ID, binding: BINDING }))).kind).toBe('invalid-response');
  });

  test.each([
    [404, 'there is no workout plan proposal'],
    [409, 'this proposal has expired: ask the coach for a new one'],
    [409, 'this approval is for a different version of the proposal than the one proposed'],
    [409, 'this proposal was already approved'],
    [409, 'this proposal was rejected: ask the coach for a new one'],
    [409, 'the workout plan this proposal replaces was changed or cancelled since it was proposed: ask the coach for a new one'],
    [409, 'this proposal can no longer be saved: exercise 12 is no longer available'],
    [401, 'could not validate credentials'],
    [422, 'binding: String should match pattern'],
  ])('a %s answer throws, so nothing after it can go on as if it were saved: %s', async (status, detail) => {
    backend.on('POST', PATH, { status, body: { detail } });

    const error = await failure(approveProposal(SESSION, { proposalId: PROPOSAL_ID, binding: BINDING }));

    expect([error.kind, error.status, error.detail]).toEqual(['http', status, detail]);
  });

  test('a 201 whose plan cannot be read is not taken for a saved plan', async () => {
    backend.on('POST', PATH, { status: 201, body: { id: 77 } });

    expect((await failure(approveProposal(SESSION, { proposalId: PROPOSAL_ID, binding: BINDING }))).kind).toBe('invalid-response');
  });

  test('no answer is a timeout and no connection a network error, both as errors', async () => {
    backend.on('POST', PATH, 'network-error');

    expect((await failure(approveProposal(SESSION, { proposalId: PROPOSAL_ID, binding: BINDING }))).kind).toBe('network');
  });

  test.each([
    ['an id that is not 32 hex digits', '../../users', BINDING],
    ['a binding that is not 64 hex digits', PROPOSAL_ID, 'nope'],
  ])('is not sent with %s', async (_name, proposalId, binding) => {
    const error = await failure(approveProposal(SESSION, { proposalId, binding }));

    expect(error.status).toBe(422);
    expect(backend.requests).toHaveLength(0);
  });
});

describe('POST /coach/proposals/{id}/reject', () => {
  const PATH = `/coach/proposals/${PROPOSAL_ID}/reject`;

  test('sends only the binding, with the token, and is done when the backend says 204', async () => {
    backend.on('POST', PATH, { status: 204 });

    await expect(rejectProposal(SESSION, { proposalId: PROPOSAL_ID, binding: BINDING })).resolves.toBeUndefined();

    const [request] = backend.requests;
    expect(request.method).toBe('POST');
    expect(request.url).toBe(`${API_BASE_URL}${PATH}`);
    expect(request.headers.Authorization).toBe(`Bearer ${SESSION.token}`);
    expect(request.body).toEqual({ binding: BINDING });
  });

  test.each([
    [404, 'there is no workout plan proposal'],
    [409, 'this proposal was already approved: it cannot be rejected'],
    [409, 'this rejection is for a different version of the proposal than the one proposed'],
    [401, 'could not validate credentials'],
    [422, 'binding: String should match pattern'],
    [503, 'unavailable'],
  ])('a %s answer throws, so nothing after it can go on as if it were dismissed: %s', async (status, detail) => {
    backend.on('POST', PATH, { status, body: { detail } });

    const error = await failure(rejectProposal(SESSION, { proposalId: PROPOSAL_ID, binding: BINDING }));

    expect([error.kind, error.status, error.detail]).toEqual(['http', status, detail]);
  });

  test('no connection is a network error', async () => {
    backend.on('POST', PATH, 'network-error');

    expect((await failure(rejectProposal(SESSION, { proposalId: PROPOSAL_ID, binding: BINDING }))).kind).toBe('network');
  });

  test.each([
    ['an id that is not 32 hex digits', '../../users', BINDING],
    ['a binding that is not 64 hex digits', PROPOSAL_ID, 'nope'],
  ])('is not sent with %s', async (_name, proposalId, binding) => {
    const error = await failure(rejectProposal(SESSION, { proposalId, binding }));

    expect(error.status).toBe(422);
    expect(backend.requests).toHaveLength(0);
  });
});

describe('GET /coach/proposals/pending', () => {
  const PATH = '/coach/proposals/pending';

  test('asks with the token and nothing else, and reads none as an empty list', async () => {
    backend.on('GET', PATH, { status: 200, body: pendings.none });

    expect(await getPendingProposals(SESSION)).toEqual([]);

    const [request] = backend.requests;
    expect(`${request.method} ${request.path}`).toBe(`GET ${PATH}`);
    expect(request.headers.Authorization).toBe(`Bearer ${SESSION.token}`);
    expect(request.body).toBeUndefined();
  });

  test('reads one waiting proposal in full: the card, its binding, its comparison and when it was made', async () => {
    backend.on('GET', PATH, { status: 200, body: pendings.one });

    const [only] = await getPendingProposals(SESSION);

    expect(only).toMatchObject({
      proposal_id: PROPOSAL_ID,
      binding: BINDING,
      name: 'Core Stability & Abs',
      created_at: '2026-10-22T12:00:00Z',
      expires_at: '2026-10-22T12:30:00Z',
      revision: { replaces_plan_id: 41, replaces_plan_estimated_minutes: 17 },
    });
    expect(only.changes?.compared_with_plan_id).toBe(41);
    expect(only.exercises).toHaveLength(5);
  });

  test('keeps the backend order: the most recently made first', async () => {
    backend.on('GET', PATH, { status: 200, body: pendings.two });

    const list = await getPendingProposals(SESSION);

    expect(list.map((item) => [item.proposal_id.slice(0, 2), item.revision === null, item.changes === null])).toEqual([
      ['cc', true, true],
      ['aa', false, false],
    ]);
  });

  test.each<[string, (body: any) => void]>([
    ['no list', (body) => delete body.proposals],
    ['a list that is not a list', (body) => (body.proposals = {})],
    ['an item that is not an object', (body) => (body.proposals[0] = 'workout')],
    ['an item with no time it was made', (body) => delete body.proposals[0].created_at],
    ['an item made at a time that is not a time', (body) => (body.proposals[0].created_at = 'earlier')],
    ['an item with a proposal id that is not 32 hex digits', (body) => (body.proposals[0].proposal_id = 'abc')],
    ['an item with no coverage', (body) => delete body.proposals[1].coverage],
    ['an item whose changes are of another plan', (body) => (body.proposals[1].changes.compared_with_plan_id = 9)],
  ])('refuses the whole list for %s: a proposal missing from it would be taken for one that is not waiting', async (_name, break_) => {
    const body = clone(pendings.two) as any;
    break_(body);
    backend.on('GET', PATH, { status: 200, body });

    expect((await failure(getPendingProposals(SESSION))).kind).toBe('invalid-response');
  });

  test('reading is the same for an answer that is already parsed', () => {
    expect(readPendingProposals(pendings.two).map((item) => item.created_at)).toEqual(['2026-10-22T12:10:00Z', '2026-10-22T12:00:00Z']);
  });

  test.each([401, 500, 503])('a %s answer throws', async (status) => {
    backend.on('GET', PATH, { status, body: { detail: 'x' } });

    expect((await failure(getPendingProposals(SESSION))).status).toBe(status);
  });

  test('no connection is a network error', async () => {
    backend.on('GET', PATH, 'network-error');

    expect((await failure(getPendingProposals(SESSION))).kind).toBe('network');
  });
});

describe('the connected gateway', () => {
  const gateway = () => createApiCoachGateway(SESSION);

  test('sends, lists what is waiting, approves and rejects through the four routes, for the signed-in user', async () => {
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_with_revision });
    backend.on('GET', '/coach/proposals/pending', { status: 200, body: pendings.one });
    backend.on('POST', `/coach/proposals/${PROPOSAL_ID}/approve`, { status: 201, body: savedPlan });
    backend.on('POST', `/coach/proposals/${PROPOSAL_ID}/reject`, { status: 204 });

    await gateway().send({ message: 'hi', history: [], workoutPlanId: 41 });
    await gateway().pending();
    await gateway().approve({ proposalId: PROPOSAL_ID, binding: BINDING });
    await gateway().reject({ proposalId: PROPOSAL_ID, binding: BINDING });

    expect(backend.requests.map((request) => `${request.method} ${request.path}`)).toEqual([
      'POST /coach/message',
      'GET /coach/proposals/pending',
      `POST /coach/proposals/${PROPOSAL_ID}/approve`,
      `POST /coach/proposals/${PROPOSAL_ID}/reject`,
    ]);
    expect(backend.requests[0].body).toMatchObject({ workout_plan_id: 41 });
  });

  test("sends the device's time zone with every message, so the coach's tomorrow is the user's own", async () => {
    jest.spyOn(Intl, 'DateTimeFormat').mockImplementation(
      () => ({ resolvedOptions: () => ({ timeZone: 'Asia/Kolkata' }) }) as unknown as Intl.DateTimeFormat,
    );
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_only });

    await gateway().send({ message: 'move it to tomorrow', history: [], workoutPlanId: 41 });

    expect(backend.requests[0].body).toEqual({
      message: 'move it to tomorrow',
      history: [],
      workout_plan_id: 41,
      timezone: 'Asia/Kolkata',
    });
    jest.restoreAllMocks();
  });

  test('sends none when the device reports no zone, as before', async () => {
    jest.spyOn(Intl, 'DateTimeFormat').mockImplementation(
      () => ({ resolvedOptions: () => ({ timeZone: undefined }) }) as unknown as Intl.DateTimeFormat,
    );
    backend.on('POST', '/coach/message', { status: 200, body: golden.reply_only });

    await gateway().send({ message: 'hi', history: [] });

    expect(backend.requests[0].body).toEqual({ message: 'hi', history: [] });
    jest.restoreAllMocks();
  });

  test('never reads a saved plan: what a proposal changes comes in the proposal', () => {
    expect(gateway()).not.toHaveProperty('loadPlan');
  });

  test('has no reset: the backend keeps no conversation', () => {
    expect(gateway().reset).toBeUndefined();
  });
});
