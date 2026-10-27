import { canSend, cleanDraft, MAX_MESSAGE_LENGTH } from '../src/coach/conversation';
import { MOCK_INTRO, MOCK_SUGGESTIONS, MOCK_TYPED_REPLIES } from '../src/mock/coachMock';

describe('cleanDraft', () => {
  test('drops the spaces and line breaks around a message and keeps what is inside it', () => {
    expect(cleanDraft('  swap the plank \n')).toBe('swap the plank');
    expect(cleanDraft('first line\nsecond line')).toBe('first line\nsecond line');
  });

  test('turns a message of only blanks into nothing', () => {
    expect(cleanDraft('')).toBe('');
    expect(cleanDraft('   \n\t ')).toBe('');
  });
});

describe('canSend', () => {
  test('is true for a message with words in it', () => {
    expect(canSend('Hello', false)).toBe(true);
    expect(canSend('  hi  ', false)).toBe(true);
  });

  test('is false for an empty message or one of only blanks', () => {
    expect(canSend('', false)).toBe(false);
    expect(canSend('   ', false)).toBe(false);
    expect(canSend('\n\n', false)).toBe(false);
  });

  test('is false while something is going on that a new message would cross, whatever was typed', () => {
    expect(canSend('Hello', true)).toBe(false);
  });
});

describe('the longest message', () => {
  test("is the coach API's own limit, so what the screen accepts is never too long for the coach", () => {
    expect(MAX_MESSAGE_LENGTH).toBe(4000);
  });
});

describe('the mock conversation the screen opens with', () => {
  test('is the coach greeting, the user asking for a different ab workout, and the coach asking about the length', () => {
    expect(MOCK_INTRO.map((item) => item.kind === 'message' && item.role)).toEqual(['assistant', 'user', 'assistant']);
    const texts = MOCK_INTRO.map((item) => (item.kind === 'message' ? item.text : ''));
    expect(texts[0]).toMatch(/Formiq Coach/);
    expect(texts[1]).toMatch(/different ab workout/);
    expect(texts[2]).toMatch(/same duration, or try a different length/);
  });

  test('has unique ids', () => {
    const ids = MOCK_INTRO.map((item) => item.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  test('offers the two answers to the coach\'s question and a way to ask for a new workout, each knowing whether it is a request for a workout', () => {
    expect(MOCK_SUGGESTIONS.map((reply) => [reply.label, reply.expectsWorkout ?? false])).toEqual([
      ['Keep same duration', true],
      ['Try different length', false],
      ['Create a 25-minute upper-body workout', true],
    ]);
  });

  // The coach only proposes, and only the user's approval saves a plan: a line that said otherwise would show the
  // screen doing what the product never does.
  test('the lines for typed messages claim to have read no data, and to have built, changed, approved or saved nothing, and say this is a preview', () => {
    for (const reply of MOCK_TYPED_REPLIES) {
      expect(reply).not.toMatch(/\b(I've|I have|I)\s+(created|built|made|saved|changed|updated|replaced|approved|looked|checked|found)\b/i);
      expect(reply).toMatch(/preview|isn't connected|is connected|For now/i);
    }
  });
});
