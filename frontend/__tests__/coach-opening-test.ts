import { coachOpening } from '../src/coach/opening';

describe('what the connected coach opens with', () => {
  test('a greeting of the app\'s own, not sent to the coach, and ways to ask for a workout, when no workout was opened', () => {
    const opening = coachOpening(null);

    expect(opening.items).toHaveLength(1);
    expect(opening.items[0]).toMatchObject({ kind: 'message', role: 'assistant', inHistory: false });
    expect(opening.suggestions.map((reply) => [reply.label, reply.expectsWorkout])).toEqual([
      ['Create a 25-minute upper-body workout', true],
      ['Suggest a different workout for today', true],
    ]);
  });

  test("the greeting claims nothing about the user's data, nothing done, and nothing saved", () => {
    const greeting = coachOpening(null).items[0];

    expect(greeting.kind === 'message' && greeting.text).not.toMatch(/\b(I've|I have|I)\s+(created|built|made|saved|changed|updated|looked|checked|found|read)\b/i);
    expect(greeting.kind === 'message' && greeting.text).not.toMatch(/your (workout|plan|data|history)s? (is|are|was|were)\b/i);
  });

  // the workout travels in its own field (workout_plan_id), so the question that names it is the screen's way of
  // showing which workout this is about, and nothing the coach is told as part of the conversation
  test('a question that names the workout, not sent to the coach as something said, when one was opened', () => {
    const opening = coachOpening({ workoutId: 41, title: 'Core & Abs Focus' });

    expect(opening.items).toEqual([
      { kind: 'message', id: 'm1', role: 'assistant', text: 'What would you like to change in “Core & Abs Focus”?', inHistory: false },
    ]);
    expect(opening.suggestions.map((reply) => reply.label)).toEqual(['Make it shorter', 'Make it easier', 'Suggest a different workout']);
  });

  test("gives the workout's title exactly as the plan has it", () => {
    const title = "Push & Pull: Day 1 (Dave's)";

    expect(coachOpening({ workoutId: 3, title }).items[0]).toMatchObject({ text: `What would you like to change in “${title}”?` });
  });

  test('a workout with no saved id (an example one) is opened as no workout in particular', () => {
    expect(coachOpening({ workoutId: 'mock-workout-today', title: 'Core & Abs Focus' })).toEqual(coachOpening(null));
  });

  test('every reply asks for a workout, so the card shows loading while the coach works', () => {
    for (const launch of [null, { workoutId: 1, title: 'x' }]) {
      expect(coachOpening(launch).suggestions.every((reply) => reply.expectsWorkout === true)).toBe(true);
    }
  });

  test('every reply has its own id and the ids of the items are unique', () => {
    for (const launch of [null, { workoutId: 1, title: 'x' }]) {
      const opening = coachOpening(launch);
      const ids = opening.suggestions.map((reply) => reply.id);
      expect(new Set(ids).size).toBe(ids.length);
    }
  });
});
